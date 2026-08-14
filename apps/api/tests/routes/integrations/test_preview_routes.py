# apps/api/tests/routes/integrations/test_preview_routes.py

"""Gmail message preview route coverage: scoping, sanitization, bounds, audit."""

from typing import Any

import pytest
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import integrations.gmail.operations.preview_message as preview_message_module
from core.exceptions.integration import IntegrationValidationError
from core.settings import settings
from models.audit_event import AuditEvent
from models.workspace import WorkspaceRole
from tests.factories import build_external_credential, build_integration_connection
from tests.routes.integrations.conftest import create_identity

pytestmark = pytest.mark.asyncio

HOSTILE_HTML = (
    '<div style="color:red">'
    "<script>alert(1)</script>"
    '<img src="x" onerror="alert(2)">'
    '<form action="https://evil.example"><input name="password"></form>'
    '<meta http-equiv="refresh" content="0;url=https://evil.example">'
    '<a href="javascript:alert(3)">click</a>'
    '<a href="https://example.com">safe link</a>'
    '<iframe src="https://evil.example"></iframe>'
    '<img src="https://tracker.example/pixel.gif">'
    "</div>"
)


async def _gmail_connection(
    db: AsyncSession,
    identity: dict[str, object],
    *,
    provider_key: str = "gmail",
):
    credential = build_external_credential(provider_key=provider_key)
    connection = build_integration_connection(
        credential=credential,
        user=identity["user"],
        workspace=identity["workspace"],
        status="active",
    )
    db.add_all([credential, connection])
    await db.commit()
    return connection


def _stub_preview(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> None:
    async def fake_preview_message(client: Any, *, message_id: str) -> dict[str, Any]:
        return payload

    monkeypatch.setattr(preview_message_module, "preview_message", fake_preview_message)


async def test_preview_sanitizes_html_and_returns_meta(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = await _gmail_connection(db_session, integration_identity)
    _stub_preview(
        monkeypatch,
        {
            "content_type": "html",
            "content": HOSTILE_HTML,
            "meta": {
                "subject": "Quarterly update",
                "labels": ["Inbox", "Clients"],
                "thread_message_count": 3,
            },
        },
    )

    response = await db_async_client.get(
        f"/api/v1/integrations/connections/{connection.id}/previews/gmail_message",
        params={"ref": "message-1"},
        headers=integration_identity["headers"],
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "gmail_message"
    assert body["content_type"] == "html"
    content = body["content"]
    assert "<script" not in content
    assert "onerror" not in content
    assert "<form" not in content
    assert "<meta" not in content
    assert "<iframe" not in content
    assert "javascript:" not in content
    assert 'href="https://example.com"' in content
    assert 'rel="noopener noreferrer nofollow"' in content
    # The tracking pixel survives server-side; the client CSP layer governs loading.
    assert 'src="https://tracker.example/pixel.gif"' in content
    assert 'style="color:red"' in content
    assert body["meta"]["labels"] == ["Inbox", "Clients"]
    assert body["meta"]["thread_message_count"] == 3


async def test_successful_preview_records_no_audit_row(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = await _gmail_connection(db_session, integration_identity)
    _stub_preview(
        monkeypatch,
        {"content_type": "text", "content": "secret body text", "meta": {}},
    )

    response = await db_async_client.get(
        f"/api/v1/integrations/connections/{connection.id}/previews/gmail_message",
        params={"ref": "message-9"},
        headers=integration_identity["headers"],
    )
    assert response.status_code == 200, response.text

    # The governed tool call already audited the read; per-render previews stay quiet.
    events = (
        await db_session.scalars(
            select(AuditEvent).where(AuditEvent.resource_id == str(connection.id))
        )
    ).all()
    assert events == []


async def test_failed_preview_commits_failure_audit_before_request_rollback(
    app: FastAPI,
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with committed_db_session_factory() as setup_db:
        user, workspace, _membership, headers = await create_identity(
            setup_db,
            role=WorkspaceRole.OWNER,
        )
        connection = await _gmail_connection(
            setup_db,
            {"user": user, "workspace": workspace},
        )

    async def fail_preview_message(client: Any, *, message_id: str) -> dict[str, Any]:
        raise IntegrationValidationError(
            "Gmail returned an invalid message",
            provider_key="gmail",
            operation="preview_message",
        )

    monkeypatch.setattr(preview_message_module, "preview_message", fail_preview_message)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            f"/api/v1/integrations/connections/{connection.id}/previews/gmail_message",
            params={"ref": "message-10"},
            headers=headers,
        )
    assert response.status_code == 400

    async with committed_db_session_factory() as verification_db:
        events = (
            await verification_db.scalars(
                select(AuditEvent).where(AuditEvent.resource_id == str(connection.id))
            )
        ).all()
    assert len(events) == 1
    assert events[0].status == "failure"
    assert events[0].details == {
        "provider_key": "gmail",
        "provider_operation": "preview_gmail_message",
        "external_ref": "message-10",
        "error_code": "IntegrationValidationError",
    }


async def test_preview_enforces_size_bound(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = await _gmail_connection(db_session, integration_identity)
    _stub_preview(
        monkeypatch,
        {"content_type": "html", "content": "<p>" + "x" * 64 + "</p>", "meta": {}},
    )
    monkeypatch.setattr(settings, "INTEGRATION_PREVIEW_MAX_BYTES", 16)

    response = await db_async_client.get(
        f"/api/v1/integrations/connections/{connection.id}/previews/gmail_message",
        params={"ref": "message-1"},
        headers=integration_identity["headers"],
    )
    assert response.status_code == 400


async def test_preview_404_for_non_gmail_connection(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    connection = await _gmail_connection(
        db_session, integration_identity, provider_key="test_provider"
    )

    response = await db_async_client.get(
        f"/api/v1/integrations/connections/{connection.id}/previews/gmail_message",
        params={"ref": "message-1"},
        headers=integration_identity["headers"],
    )
    assert response.status_code == 404


async def test_preview_404_for_kind_not_contributed_by_provider(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    connection = await _gmail_connection(db_session, integration_identity)

    response = await db_async_client.get(
        f"/api/v1/integrations/connections/{connection.id}/previews/unknown_kind",
        params={"ref": "message-1"},
        headers=integration_identity["headers"],
    )
    assert response.status_code == 404


async def test_preview_404_outside_workspace_visibility(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    connection = await _gmail_connection(db_session, integration_identity)
    _outsider, _workspace, _membership, outsider_headers = await create_identity(
        db_session,
        role=WorkspaceRole.OWNER,
    )

    response = await db_async_client.get(
        f"/api/v1/integrations/connections/{connection.id}/previews/gmail_message",
        params={"ref": "message-1"},
        headers=outsider_headers,
    )
    assert response.status_code == 404


async def test_preview_rejects_malformed_refs(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    connection = await _gmail_connection(db_session, integration_identity)

    response = await db_async_client.get(
        f"/api/v1/integrations/connections/{connection.id}/previews/gmail_message",
        params={"ref": "../escape attempt"},
        headers=integration_identity["headers"],
    )
    assert response.status_code == 422


async def test_preview_requires_authentication(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    connection = await _gmail_connection(db_session, integration_identity)

    response = await db_async_client.get(
        f"/api/v1/integrations/connections/{connection.id}/previews/gmail_message",
        params={"ref": "message-1"},
    )
    assert response.status_code == 401
