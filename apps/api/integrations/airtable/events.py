# apps/api/integrations/airtable/events.py

"""Airtable webhook lifecycle, exact-byte verification, and payload polling."""

import base64
import hashlib
import hmac
import ipaddress
import json
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationConnectionError,
    IntegrationValidationError,
)
from core.settings import settings
from models.integrations import (
    ExternalCredential,
    IntegrationConnection,
    IntegrationEvent,
    IntegrationResource,
    IntegrationWebhook,
)
from services.integrations.events.domain import WebhookVerificationError
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.plugin import (
    IntegrationEventDefinition,
    IntegrationEventRequest,
    ProcessedIntegrationEvent,
    VerifiedIntegrationEvent,
)
from services.secrets import delete_secret, resolve_secret, write_secret
from services.secrets.domain import SecretReference

from .client import AirtableClient

_DATETIME_ADAPTER = TypeAdapter(datetime)
_CONTENT_MAC_HEADER = "x-airtable-content-mac"
_MAX_PAYLOADS_PER_REQUEST = 50


async def create_webhook(
    db: AsyncSession,
    connection: IntegrationConnection,
    resource: IntegrationResource,
) -> IntegrationWebhook:
    """Create a base webhook and persist its one-time MAC secret by reference."""
    if connection.provider_key != "airtable" or resource.connection_id != connection.id:
        raise IntegrationValidationError(
            "Airtable webhook resource does not belong to the connection",
            provider_key="airtable",
            connection_id=str(connection.id),
            operation="create_webhook",
        )
    if resource.resource_type != "airtable_base" or resource.availability != "available":
        raise IntegrationValidationError(
            "Airtable webhooks require an available base",
            provider_key="airtable",
            connection_id=str(connection.id),
            operation="create_webhook",
        )
    receipt_id = uuid4().hex
    notification_url = (
        f"{settings.APP_BASE_URL.rstrip('/')}{settings.API_V1_PREFIX}"
        f"/integrations/events/airtable/{receipt_id}"
    )
    _validate_notification_url(notification_url)
    client = await _client_for_connection(db, connection)
    response = await client.post(
        f"bases/{resource.external_id}/webhooks",
        operation="create_webhook",
        policy=IntegrationRequestPolicy.MUTATION,
        json={
            "notificationUrl": notification_url,
            "specification": {
                "options": {
                    "filters": {
                        "dataTypes": ["tableData"],
                    }
                }
            },
        },
    )
    external_webhook_id = _required_string(response, "id", operation="create_webhook")
    mac_secret = _required_string(response, "macSecretBase64", operation="create_webhook")
    secret_name = f"integrations/airtable/{connection.id}/webhook/{external_webhook_id}"
    try:
        secret_ref = await write_secret(
            db,
            name=secret_name,
            value=mac_secret,
            workspace_id=connection.owner_workspace_id,
            actor_id=connection.connected_by_user_id,
        )
    except Exception:
        with suppress(Exception):
            await client.delete(
                f"bases/{resource.external_id}/webhooks/{external_webhook_id}",
                operation="delete_orphaned_webhook",
                policy=IntegrationRequestPolicy.MUTATION,
            )
        raise

    webhook = IntegrationWebhook(
        provider_key="airtable",
        connection_id=connection.id,
        resource_id=resource.id,
        external_resource_id=resource.external_id,
        receipt_id=receipt_id,
        external_webhook_id=external_webhook_id,
        secret_provider=secret_ref.provider,
        secret_name=secret_ref.name,
        secret_version=secret_ref.version,
        status="active",
        expires_at=_optional_datetime(response, "expirationTime"),
    )
    db.add(webhook)
    await db.flush()
    return webhook


async def refresh_webhook(db: AsyncSession, webhook: IntegrationWebhook) -> None:
    """Extend one active Airtable webhook and update its durable expiry."""
    connection = await _active_connection(db, webhook)
    client = await _client_for_connection(db, connection)
    response = await client.post(
        (f"bases/{webhook.external_resource_id}/webhooks/{webhook.external_webhook_id}/refresh"),
        operation="refresh_webhook",
        policy=IntegrationRequestPolicy.MUTATION,
    )
    webhook.expires_at = _optional_datetime(response, "expirationTime")
    webhook.last_refreshed_at = datetime.now(UTC)
    webhook.last_error_code = None
    await db.flush()


async def delete_webhook(db: AsyncSession, webhook: IntegrationWebhook) -> None:
    """Delete one Airtable webhook and its verification secret."""
    connection = await db.get(IntegrationConnection, webhook.connection_id)
    if connection is not None and not connection.deleted:
        client = await _client_for_connection(db, connection)
        await client.delete(
            (f"bases/{webhook.external_resource_id}/webhooks/{webhook.external_webhook_id}"),
            operation="delete_webhook",
            policy=IntegrationRequestPolicy.MUTATION,
        )
    await delete_secret(
        db,
        webhook.secret_reference,
        workspace_id=connection.owner_workspace_id if connection is not None else None,
        actor_id=connection.connected_by_user_id if connection is not None else None,
    )
    webhook.status = "disabled"
    webhook.expires_at = None
    await db.flush()


async def verify_event(
    db: AsyncSession,
    webhook: IntegrationWebhook,
    request: IntegrationEventRequest,
) -> VerifiedIntegrationEvent:
    """Authenticate exact receipt bytes before parsing the notification JSON."""
    supplied_mac = request.headers.get(_CONTENT_MAC_HEADER, "")
    if not supplied_mac:
        raise WebhookVerificationError("missing_signature")
    try:
        encoded_secret = await resolve_secret(
            db,
            webhook.secret_reference,
            workspace_id=(await _active_connection(db, webhook)).owner_workspace_id,
        )
        secret = base64.b64decode(encoded_secret, validate=True)
    except Exception as exc:
        raise WebhookVerificationError("invalid_secret_reference") from exc
    expected_mac = (
        "hmac-sha256="
        + hmac.new(
            secret,
            request.raw_body,
            hashlib.sha256,
        ).hexdigest()
    )
    if not hmac.compare_digest(supplied_mac, expected_mac):
        raise WebhookVerificationError("invalid_signature")

    try:
        parsed = json.loads(request.raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WebhookVerificationError("invalid_json") from exc
    if not isinstance(parsed, dict):
        raise WebhookVerificationError("invalid_payload")
    base = parsed.get("base")
    hook = parsed.get("webhook")
    timestamp = parsed.get("timestamp")
    if (
        not isinstance(base, dict)
        or not isinstance(hook, dict)
        or base.get("id") != webhook.external_resource_id
        or hook.get("id") != webhook.external_webhook_id
        or not isinstance(timestamp, str)
        or not timestamp.strip()
    ):
        raise WebhookVerificationError("registration_mismatch")
    try:
        _DATETIME_ADAPTER.validate_python(timestamp)
    except ValidationError as exc:
        raise WebhookVerificationError("invalid_timestamp") from exc

    dedup_key = hashlib.sha256(f"{webhook.external_webhook_id}:{timestamp}".encode()).hexdigest()
    return VerifiedIntegrationEvent(
        connection_id=webhook.connection_id,
        external_event_id=timestamp,
        external_resource_id=webhook.external_resource_id,
        event_type="airtable.webhook_notification",
        dedup_key=dedup_key,
        payload={
            "base": {"id": webhook.external_resource_id},
            "webhook": {"id": webhook.external_webhook_id},
            "timestamp": timestamp,
        },
    )


async def process_event(
    db: AsyncSession,
    webhook: IntegrationWebhook,
    _event: IntegrationEvent,
) -> ProcessedIntegrationEvent:
    """Pull all currently available payloads and atomically advance the cursor."""
    connection = await _active_connection(db, webhook)
    client = await _client_for_connection(db, connection)
    cursor = webhook.payload_cursor
    payloads: list[object] = []
    for _page in range(settings.INTEGRATIONS_EVENT_MAX_PAYLOAD_PAGES):
        params: dict[str, object] = {"limit": _MAX_PAYLOADS_PER_REQUEST}
        if cursor is not None:
            params["cursor"] = cursor
        response = await client.get(
            (
                f"bases/{webhook.external_resource_id}/webhooks/"
                f"{webhook.external_webhook_id}/payloads"
            ),
            operation="list_webhook_payloads",
            policy=IntegrationRequestPolicy.READ,
            params=params,
        )
        if not isinstance(response, dict):
            raise IntegrationValidationError(
                "Airtable returned an invalid webhook payload response",
                provider_key="airtable",
                connection_id=str(connection.id),
                operation="list_webhook_payloads",
            )
        page_payloads = response.get("payloads")
        next_cursor = response.get("cursor")
        might_have_more = response.get("mightHaveMore")
        if (
            not isinstance(page_payloads, list)
            or not isinstance(next_cursor, int)
            or not isinstance(might_have_more, bool)
        ):
            raise IntegrationValidationError(
                "Airtable returned an incomplete webhook payload response",
                provider_key="airtable",
                connection_id=str(connection.id),
                operation="list_webhook_payloads",
            )
        payloads.extend(page_payloads)
        cursor = next_cursor
        if not might_have_more:
            break
    else:
        raise IntegrationValidationError(
            "Airtable webhook payload page limit was exceeded",
            provider_key="airtable",
            connection_id=str(connection.id),
            operation="list_webhook_payloads",
        )

    webhook.payload_cursor = cursor
    webhook.last_refreshed_at = datetime.now(UTC)
    normalized = {
        "cursor": cursor,
        "payload_count": len(payloads),
        "payloads": payloads,
    }
    encoded = json.dumps(normalized, separators=(",", ":"), default=str).encode()
    if len(encoded) > settings.INTEGRATIONS_EVENT_PAYLOAD_MAX_BYTES:
        normalized = {
            "cursor": cursor,
            "payload_count": len(payloads),
            "payload_omitted": True,
        }
    return ProcessedIntegrationEvent(payload=normalized)


async def _client_for_connection(
    db: AsyncSession,
    connection: IntegrationConnection,
) -> AirtableClient:
    credential = await db.get(ExternalCredential, connection.credential_id)
    if credential is None or credential.deleted or credential.auth_mode != "api_key":
        raise IntegrationAuthError(
            "Airtable connection needs to be reconnected",
            provider_key="airtable",
            connection_id=str(connection.id),
            operation="webhook",
        )
    reference = SecretReference(
        provider=credential.secret_provider or "",
        name=credential.secret_name or "",
        version=credential.secret_version or "",
    )

    async def access_token() -> str:
        return await resolve_secret(
            db,
            reference,
            workspace_id=connection.owner_workspace_id,
            actor_id=connection.connected_by_user_id,
        )

    return AirtableClient(access_token)


async def _active_connection(
    db: AsyncSession,
    webhook: IntegrationWebhook,
) -> IntegrationConnection:
    connection = await db.get(IntegrationConnection, webhook.connection_id)
    if (
        connection is None
        or connection.deleted
        or connection.provider_key != "airtable"
        or connection.status
        in {
            "revoked",
            "needs_reauth",
            "needs_credential",
            "auth_pending",
        }
    ):
        raise IntegrationConnectionError(
            "Airtable webhook connection is not active",
            provider_key="airtable",
            connection_id=str(webhook.connection_id),
            operation="webhook",
        )
    return connection


def _validate_notification_url(value: str) -> None:
    parsed = urlsplit(value)
    hostname = parsed.hostname
    if parsed.scheme != "https" or not hostname:
        raise IntegrationValidationError(
            "Airtable webhook notification URL must be a public HTTPS URL",
            provider_key="airtable",
            operation="create_webhook",
        )
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise IntegrationValidationError(
            "Airtable webhook notification URL must be publicly reachable",
            provider_key="airtable",
            operation="create_webhook",
        )
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return
    if not address.is_global:
        raise IntegrationValidationError(
            "Airtable webhook notification URL must be publicly reachable",
            provider_key="airtable",
            operation="create_webhook",
        )


def _required_string(payload: Any, key: str, *, operation: str) -> str:
    value = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise IntegrationValidationError(
            f"Airtable response is missing {key}",
            provider_key="airtable",
            operation=operation,
        )
    return value.strip()


def _optional_datetime(payload: Any, key: str) -> datetime | None:
    value = payload.get(key) if isinstance(payload, dict) else None
    if value is None:
        return None
    try:
        parsed = _DATETIME_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise IntegrationValidationError(
            f"Airtable response has an invalid {key}",
            provider_key="airtable",
            operation="webhook_lifecycle",
        ) from exc
    return parsed


EVENT_DEFINITION = IntegrationEventDefinition(
    verify=verify_event,
    process=process_event,
    create_webhook=create_webhook,
    refresh_webhook=refresh_webhook,
    delete_webhook=delete_webhook,
)
