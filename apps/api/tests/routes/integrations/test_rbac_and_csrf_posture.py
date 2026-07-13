"""RBAC ownership and unchanged CSRF posture for integration routes."""

from pathlib import Path

import pytest
from httpx2 import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.security import SecurityEvent
from models.workspace import WorkspaceRole
from tests.routes.integrations.conftest import create_identity
from utils.security import generate_csrf_token

pytestmark = pytest.mark.asyncio


async def test_oauth_callback_is_post_only(db_async_client: AsyncClient) -> None:
    response = await db_async_client.get("/api/v1/integrations/oauth/callback")
    assert response.status_code == 405


async def test_member_can_connect_user_provider_but_not_workspace_provider(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    _user, _workspace, _membership, headers = await create_identity(
        db_session,
        role=WorkspaceRole.MEMBER,
        workspace=integration_identity["workspace"],
    )
    gmail = await db_async_client.post(
        "/api/v1/integrations/connections/oauth/start",
        headers=headers,
        json={"provider_key": "gmail", "owner_scope": "user", "label": "My inbox"},
    )
    assert gmail.status_code == 200, gmail.text

    google_ads = await db_async_client.post(
        "/api/v1/integrations/connections/oauth/start",
        headers=headers,
        json={
            "provider_key": "google_ads",
            "owner_scope": "workspace",
            "label": "Company ads",
        },
    )
    assert google_ads.status_code == 403


async def test_read_only_can_list_but_cannot_mutate(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    _user, _workspace, _membership, headers = await create_identity(
        db_session,
        role=WorkspaceRole.READ_ONLY,
        workspace=integration_identity["workspace"],
    )
    listed = await db_async_client.get("/api/v1/integrations/connections", headers=headers)
    assert listed.status_code == 200

    mutation = await db_async_client.post(
        "/api/v1/integrations/connections/oauth/start",
        headers=headers,
        json={"provider_key": "gmail", "owner_scope": "user", "label": "Denied"},
    )
    assert mutation.status_code == 403


async def test_non_owner_member_cannot_mutate_user_connection(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    workspace = integration_identity["workspace"]
    _owner, _workspace, _membership, owner_headers = await create_identity(
        db_session,
        role=WorkspaceRole.MEMBER,
        workspace=workspace,
    )
    started = await db_async_client.post(
        "/api/v1/integrations/connections/oauth/start",
        headers=owner_headers,
        json={"provider_key": "gmail", "owner_scope": "user", "label": "Owner inbox"},
    )
    assert started.status_code == 200

    _other, _workspace, _membership, other_headers = await create_identity(
        db_session,
        role=WorkspaceRole.MEMBER,
        workspace=workspace,
    )
    renamed = await db_async_client.patch(
        f"/api/v1/integrations/connections/{started.json()['connection_id']}",
        headers=other_headers,
        json={"label": "Stolen"},
    )
    assert renamed.status_code == 404

    _admin, _workspace, _membership, admin_headers = await create_identity(
        db_session,
        role=WorkspaceRole.ADMIN,
        workspace=workspace,
    )
    admin_rename = await db_async_client.patch(
        f"/api/v1/integrations/connections/{started.json()['connection_id']}",
        headers=admin_headers,
        json={"label": "Admin takeover"},
    )
    assert admin_rename.status_code == 404


async def test_session_cookie_callback_post_requires_csrf(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    db_async_client.cookies.set("session", integration_identity["session_token"])
    rejected = await db_async_client.post(
        "/api/v1/integrations/connections/oauth/start",
        headers={"origin": "http://localhost:3000"},
        json={"provider_key": "gmail", "owner_scope": "user", "label": "No CSRF"},
    )
    assert rejected.status_code == 403
    assert rejected.json()["reason"] == "X-CSRF-Token header missing"

    callback = await db_async_client.post(
        "/api/v1/integrations/oauth/callback",
        json={"state": "invalid-state", "error": "access_denied"},
    )
    assert callback.status_code == 403

    csrf_token = generate_csrf_token(integration_identity["session_token"])
    db_async_client.cookies.set("csrf", csrf_token)
    accepted_by_csrf = await db_async_client.post(
        "/api/v1/integrations/oauth/callback",
        headers={
            "origin": "http://localhost:3000",
            "x-csrf-token": csrf_token,
            "x-workspace": integration_identity["workspace"].slug,
        },
        json={"state": "invalid-state", "error": "access_denied"},
    )
    assert accepted_by_csrf.status_code == 401
    invalid_state_events = await db_session.scalar(
        select(func.count())
        .select_from(SecurityEvent)
        .where(SecurityEvent.event_type == "integration_oauth_state_invalid")
    )
    assert invalid_state_events == 1


async def test_csrf_exempt_paths_do_not_include_integrations() -> None:
    source = (Path(__file__).parents[3] / "middleware" / "csrf.py").read_text()
    assert "/integrations" not in source
