"""Airtable webhook verification and payload cursor behavior."""

# ruff: noqa: S106 - inert secret-reference metadata in test models

import base64
import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from core.exceptions.integration import IntegrationValidationError
from integrations.airtable import events
from models.integrations import (
    IntegrationConnection,
    IntegrationEvent,
    IntegrationResource,
    IntegrationWebhook,
)
from services.integrations.events.domain import WebhookVerificationError
from services.integrations.plugin import IntegrationEventRequest
from services.secrets.domain import SecretReference


def _request(raw_body: bytes, secret: bytes, *, valid: bool = True) -> IntegrationEventRequest:
    digest = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    if not valid:
        digest = "0" * 64
    return IntegrationEventRequest(
        headers={"x-airtable-content-mac": f"hmac-sha256={digest}"},
        raw_body=raw_body,
        payload_digest=hashlib.sha256(raw_body).hexdigest(),
        request_url="https://api.example.test/api/v1/integrations/events/airtable/ach1",
    )


@pytest.mark.asyncio
async def test_create_webhook_stores_only_the_mac_secret_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(events.settings, "APP_BASE_URL", "https://api.example.test")
    connection = IntegrationConnection(
        id=uuid4(),
        provider_key="airtable",
        owner_workspace_id=uuid4(),
        connected_by_user_id=uuid4(),
    )
    resource = IntegrationResource(
        id=uuid4(),
        connection_id=connection.id,
        resource_type="airtable_base",
        external_id="app1",
        availability="available",
    )
    post = AsyncMock(
        return_value={
            "id": "ach1",
            "macSecretBase64": "one-time-secret",
            "expirationTime": "2026-07-31T08:00:00Z",
        }
    )
    write = AsyncMock(
        return_value=SecretReference(
            provider="local",
            name="integrations/airtable/test/webhook/ach1",
            version="00000001",
        )
    )
    db = SimpleNamespace(add=AsyncMock(), flush=AsyncMock())
    db.add = lambda value: setattr(db, "added", value)

    async def client(*_args, **_kwargs):
        return SimpleNamespace(post=post)

    monkeypatch.setattr(events, "_client_for_connection", client)
    monkeypatch.setattr(events, "write_secret", write)

    webhook = await events.create_webhook(
        db,  # type: ignore[arg-type]
        connection,
        resource,
    )

    write.assert_awaited_once()
    assert write.await_args.kwargs["value"] == "one-time-secret"
    assert webhook.external_webhook_id == "ach1"
    assert len(webhook.receipt_id) == 32
    assert webhook.secret_reference == write.return_value
    assert "one-time-secret" not in repr(webhook.__dict__)
    post.assert_awaited_once()
    assert post.await_args.kwargs["json"]["notificationUrl"].endswith(
        f"/integrations/events/airtable/{webhook.receipt_id}"
    )
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_webhook_rejects_local_callback_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(events.settings, "APP_BASE_URL", "http://localhost:8000")
    connection = IntegrationConnection(
        id=uuid4(),
        provider_key="airtable",
        owner_workspace_id=uuid4(),
        connected_by_user_id=uuid4(),
    )
    resource = IntegrationResource(
        id=uuid4(),
        connection_id=connection.id,
        resource_type="airtable_base",
        external_id="app1",
        availability="available",
    )

    with pytest.raises(IntegrationValidationError, match="public HTTPS"):
        await events.create_webhook(  # type: ignore[arg-type]
            SimpleNamespace(),
            connection,
            resource,
        )


@pytest.mark.asyncio
async def test_refresh_and_delete_webhook_update_lifecycle_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = SimpleNamespace(
        id=uuid4(),
        deleted=False,
        owner_workspace_id=uuid4(),
        connected_by_user_id=uuid4(),
    )
    webhook = IntegrationWebhook(
        id=uuid4(),
        provider_key="airtable",
        connection_id=connection.id,
        external_resource_id="app1",
        receipt_id=uuid4().hex,
        external_webhook_id="ach1",
        secret_provider="local",
        secret_name="test/webhook",
        secret_version="00000001",
        status="active",
    )
    post = AsyncMock(return_value={"expirationTime": "2026-08-01T08:00:00Z"})
    delete = AsyncMock(return_value={})
    delete_secret = AsyncMock(return_value=True)
    client_value = SimpleNamespace(post=post, delete=delete)
    db = SimpleNamespace(
        get=AsyncMock(return_value=connection),
        flush=AsyncMock(),
    )

    async def active(*_args, **_kwargs):
        return connection

    async def client(*_args, **_kwargs):
        return client_value

    monkeypatch.setattr(events, "_active_connection", active)
    monkeypatch.setattr(events, "_client_for_connection", client)
    monkeypatch.setattr(events, "delete_secret", delete_secret)

    await events.refresh_webhook(db, webhook)  # type: ignore[arg-type]
    assert webhook.expires_at is not None
    assert webhook.last_refreshed_at is not None

    await events.delete_webhook(db, webhook)  # type: ignore[arg-type]
    assert webhook.status == "disabled"
    assert webhook.expires_at is None
    delete.assert_awaited_once()
    delete_secret.assert_awaited_once()


@pytest.mark.asyncio
async def test_verify_event_authenticates_exact_bytes_before_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = b"airtable-mac-secret"
    webhook = IntegrationWebhook(
        id=uuid4(),
        provider_key="airtable",
        connection_id=uuid4(),
        external_resource_id="app1",
        receipt_id=uuid4().hex,
        external_webhook_id="ach1",
        secret_provider="local",
        secret_name="test/webhook",
        secret_version="00000001",
    )
    raw_body = json.dumps(
        {
            "base": {"id": "app1"},
            "webhook": {"id": "ach1"},
            "timestamp": "2026-07-24T08:00:00.000Z",
        },
        separators=(",", ":"),
    ).encode()

    async def resolve(*_args, **_kwargs):
        return base64.b64encode(secret).decode()

    async def active(*_args, **_kwargs):
        return SimpleNamespace(owner_workspace_id=uuid4())

    monkeypatch.setattr(events, "resolve_secret", resolve)
    monkeypatch.setattr(events, "_active_connection", active)

    verified = await events.verify_event(None, webhook, _request(raw_body, secret))  # type: ignore[arg-type]

    assert verified.connection_id == webhook.connection_id
    assert verified.external_event_id == "2026-07-24T08:00:00.000Z"
    assert verified.dedup_key == hashlib.sha256(b"ach1:2026-07-24T08:00:00.000Z").hexdigest()

    monkeypatch.setattr(events.json, "loads", lambda _value: pytest.fail("parsed before verify"))
    with pytest.raises(WebhookVerificationError, match="verification failed"):
        await events.verify_event(  # type: ignore[arg-type]
            None,
            webhook,
            _request(raw_body, secret, valid=False),
        )


@pytest.mark.asyncio
async def test_process_event_advances_cursor_across_all_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    webhook = IntegrationWebhook(
        id=uuid4(),
        provider_key="airtable",
        connection_id=uuid4(),
        external_resource_id="app1",
        receipt_id=uuid4().hex,
        external_webhook_id="ach1",
        secret_provider="local",
        secret_name="test/webhook",
        secret_version="00000001",
        payload_cursor=4,
    )
    event = IntegrationEvent(id=uuid4())
    calls: list[dict[str, object]] = []
    responses = [
        {"cursor": 6, "mightHaveMore": True, "payloads": [{"value": 1}, {"value": 2}]},
        {"cursor": 7, "mightHaveMore": False, "payloads": [{"value": 3}]},
    ]

    class FakeClient:
        async def get(self, _path, *, operation, policy, params):
            assert operation == "list_webhook_payloads"
            assert policy == "read"
            calls.append(params)
            return responses.pop(0)

    async def active(*_args, **_kwargs):
        return SimpleNamespace(id=webhook.connection_id)

    async def client(*_args, **_kwargs):
        return FakeClient()

    monkeypatch.setattr(events, "_active_connection", active)
    monkeypatch.setattr(events, "_client_for_connection", client)

    result = await events.process_event(None, webhook, event)  # type: ignore[arg-type]

    assert calls == [{"limit": 50, "cursor": 4}, {"limit": 50, "cursor": 6}]
    assert webhook.payload_cursor == 7
    assert result.payload == {
        "cursor": 7,
        "payload_count": 3,
        "payloads": [{"value": 1}, {"value": 2}, {"value": 3}],
    }
