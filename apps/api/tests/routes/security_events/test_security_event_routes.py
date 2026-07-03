# apps/api/tests/routes/security_events/test_security_event_routes.py

"""HTTP-boundary tests for global security-event routes."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from core.settings import settings
from models.security import SecurityEvent
from models.user import User
from models.workspace import Workspace, WorkspaceRole
from services.security import SecurityEventType
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.auth import bearer_headers

pytestmark = pytest.mark.asyncio


async def _authenticated_workspace(
    db: AsyncSession,
    *,
    email: str | None = None,
    role: WorkspaceRole = WorkspaceRole.OWNER,
    workspace: Workspace | None = None,
) -> tuple[User, Workspace, dict[str, str]]:
    user = build_user(email=email or f"security-{uuid4().hex}@example.com")
    workspace = workspace or build_workspace(slug=f"security-{uuid4().hex[:8]}")
    membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=user.id,
        role=role,
    )
    db.add_all([user, workspace, membership])
    await db.flush()
    user.default_workspace_id = workspace.id
    session = await session_manager.create_session(db, str(user.id))
    await db.commit()
    return user, workspace, bearer_headers(session["session_token"])


async def _seed_security_event(
    db: AsyncSession,
    *,
    event_type: SecurityEventType,
    user_email: str | None,
    ip_address: str = "127.0.0.1",
    endpoint: str | None = "/api/v1/auth/login",
    occurred_at: datetime | None = None,
    details: dict[str, object] | None = None,
) -> SecurityEvent:
    event = SecurityEvent(
        occurred_at=occurred_at or datetime.now(UTC),
        event_type=event_type.value,
        ip_address=ip_address,
        endpoint=endpoint,
        user_email=user_email,
        user_agent="pytest",
        details=details or {"seed": True},
        request_id=f"req-{uuid4().hex[:8]}",
    )
    db.add(event)
    await db.flush()
    return event


async def test_security_events_require_super_admin(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    owner, _workspace, headers = await _authenticated_workspace(db_session)
    await _seed_security_event(
        db_session,
        event_type=SecurityEventType.AUTH_LOGIN_SUCCEEDED,
        user_email=owner.email,
    )
    await db_session.commit()

    response = await db_async_client.get("/api/v1/security-events/", headers=headers)

    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_super_admin_can_list_filter_and_read_security_events(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    super_admin_email = f"security-admin-{uuid4().hex}@example.com"
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", super_admin_email)
    _admin, _workspace, headers = await _authenticated_workspace(
        db_session,
        email=super_admin_email,
    )
    matching = await _seed_security_event(
        db_session,
        event_type=SecurityEventType.AUTH_LOGIN_FAILED,
        user_email="person@example.com",
        ip_address="127.0.0.2",
        details={"reason": "bad_password"},
    )
    await _seed_security_event(
        db_session,
        event_type=SecurityEventType.AUTH_LOGIN_SUCCEEDED,
        user_email="person@example.com",
        ip_address="127.0.0.3",
    )
    await db_session.commit()

    list_response = await db_async_client.get(
        "/api/v1/security-events/",
        headers=headers,
        params={"event_type": "auth_login_failed"},
    )

    assert list_response.status_code == 200
    body = list_response.json()
    assert body["total"] == 1
    assert body["events"][0]["id"] == str(matching.id)
    assert body["events"][0]["ip_address"] == "127.0.0.2"

    detail_response = await db_async_client.get(
        f"/api/v1/security-events/{matching.id}",
        headers=headers,
    )
    assert detail_response.status_code == 200
    assert detail_response.json()["details"] == {"reason": "bad_password"}


async def test_security_event_filter_rejects_unknown_event_type(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    super_admin_email = f"security-admin-{uuid4().hex}@example.com"
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", super_admin_email)
    _admin, _workspace, headers = await _authenticated_workspace(
        db_session,
        email=super_admin_email,
    )

    response = await db_async_client.get(
        "/api/v1/security-events/",
        headers=headers,
        params={"event_type": "typo"},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["field"] == "event_type"
    assert "auth_login_failed" in body["allowed_values"]


async def test_auth_me_reflects_super_admin_flag(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    super_admin_email = f"security-admin-{uuid4().hex}@example.com"
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", super_admin_email)
    _admin, workspace, admin_headers = await _authenticated_workspace(
        db_session,
        email=super_admin_email,
    )
    _owner, _workspace, owner_headers = await _authenticated_workspace(
        db_session,
        workspace=workspace,
    )

    admin_response = await db_async_client.get("/api/v1/auth/me", headers=admin_headers)
    assert admin_response.status_code == 200
    assert admin_response.json()["is_super_admin"] is True

    owner_response = await db_async_client.get("/api/v1/auth/me", headers=owner_headers)
    assert owner_response.status_code == 200
    assert owner_response.json()["is_super_admin"] is False
