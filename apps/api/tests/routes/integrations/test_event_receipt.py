"""Verification-first inbound integration event route."""

# ruff: noqa: S106 - inert secret-reference metadata in test models

import base64
import hashlib
import hmac
import importlib
import json
from unittest.mock import AsyncMock
from uuid import uuid4

from httpx2 import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.integrations import IntegrationEvent
from models.jobs import Job
from services.secrets import write_secret
from tests.factories import (
    build_external_credential,
    build_integration_connection,
    build_integration_resource,
    build_integration_webhook,
)


async def _seed_receipt(db: AsyncSession, identity: dict[str, object]):
    user = identity["user"]
    workspace = identity["workspace"]
    credential = build_external_credential(
        provider_key="airtable",
        auth_mode="api_key",
        access_token_encrypted=None,
        secret_provider="local",
        secret_name="test/airtable/pat",
        secret_version="00000001",
    )
    db.add(credential)
    await db.flush()
    connection = build_integration_connection(
        credential=credential,
        user=user,
        workspace=workspace,
        status="active",
    )
    db.add(connection)
    await db.flush()
    resource = build_integration_resource(
        connection=connection,
        resource_type="airtable_base",
        external_id="app1",
        enabled=True,
    )
    db.add(resource)
    await db.flush()
    secret = b"receipt-mac-secret"
    ref = await write_secret(
        db,
        name=f"integrations/airtable/{connection.id}/webhook/ach1",
        value=base64.b64encode(secret).decode(),
        workspace_id=workspace.id,
        actor_id=user.id,
    )
    webhook = build_integration_webhook(
        connection=connection,
        resource=resource,
        receipt_id="receipt1",
        external_webhook_id="ach1",
        secret_provider=ref.provider,
        secret_name=ref.name,
        secret_version=ref.version,
    )
    db.add(webhook)
    await db.commit()
    return secret


def _body() -> bytes:
    return json.dumps(
        {
            "base": {"id": "app1"},
            "webhook": {"id": "ach1"},
            "timestamp": "2026-07-24T08:00:00.000Z",
        },
        separators=(",", ":"),
    ).encode()


def _signature(body: bytes, secret: bytes) -> str:
    return "hmac-sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()


async def test_valid_duplicate_receipt_creates_one_event_and_job(
    db_async_client: AsyncClient,
    db_session: AsyncSession,
    integration_identity: dict[str, object],
) -> None:
    secret = await _seed_receipt(db_session, integration_identity)
    body = _body()
    headers = {"X-Airtable-Content-MAC": _signature(body, secret)}

    first = await db_async_client.post(
        "/api/v1/integrations/events/airtable/receipt1",
        content=body,
        headers=headers,
    )
    duplicate = await db_async_client.post(
        "/api/v1/integrations/events/airtable/receipt1",
        content=body,
        headers=headers,
    )

    assert first.status_code == duplicate.status_code == 204
    assert await db_session.scalar(select(func.count()).select_from(IntegrationEvent)) == 1
    assert (
        await db_session.scalar(
            select(func.count()).select_from(Job).where(Job.kind == "integrations.process_event")
        )
        == 1
    )


async def test_invalid_mac_is_rejected_without_event_and_records_safe_metadata(
    db_async_client: AsyncClient,
    db_session: AsyncSession,
    integration_identity: dict[str, object],
    monkeypatch,
) -> None:
    route_module = importlib.import_module("routes.integrations.receive_event")
    record_rejection = AsyncMock()
    monkeypatch.setattr(
        route_module,
        "safe_record_security_event_committed",
        record_rejection,
    )
    await _seed_receipt(db_session, integration_identity)
    body = _body()

    response = await db_async_client.post(
        "/api/v1/integrations/events/airtable/receipt1",
        content=body,
        headers={"X-Airtable-Content-MAC": "hmac-sha256=" + "0" * 64},
    )

    assert response.status_code == 401
    assert await db_session.scalar(select(func.count()).select_from(IntegrationEvent)) == 0
    record_rejection.assert_awaited_once()
    details = record_rejection.await_args.kwargs["details"]
    assert details["reason_code"] == "invalid_signature"
    assert set(details) == {
        "provider_key",
        "webhook_id_fingerprint",
        "reason_code",
        "payload_digest",
    }
    assert "receipt1" not in str(details)
    assert "x-airtable-content-mac" not in str(details).lower()


async def test_cookie_bearing_receipt_remains_csrf_protected(
    db_async_client: AsyncClient,
) -> None:
    db_async_client.cookies.set("session", uuid4().hex)

    response = await db_async_client.post(
        "/api/v1/integrations/events/airtable/ach1",
        content=_body(),
    )

    assert response.status_code == 403
