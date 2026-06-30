# apps/api/tests/routes/test_management_routes.py

"""HTTP-boundary tests for key user and workspace management routes."""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from core.settings import settings
from models.user import User
from models.workspace import WorkspaceRole
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.auth import bearer_headers

pytestmark = pytest.mark.asyncio


async def _authenticated_user(
    db_session: AsyncSession,
    *,
    email: str,
) -> tuple[User, str]:
    user = build_user(email=email)
    db_session.add(user)
    await db_session.flush()
    session = await session_manager.create_session(db_session, str(user.id))
    await db_session.commit()
    return user, session["session_token"]


async def test_user_create_route_requires_super_admin(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    _, token = await _authenticated_user(db_session, email="normal@example.com")

    response = await db_async_client.post(
        "/api/v1/users/",
        headers=bearer_headers(token),
        json={"email": "created@example.com", "password": "Password123"},
    )

    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["detail"] == "Requires super admin role"


async def test_super_admin_create_user_route_returns_public_projection(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", "admin@example.com")
    _, token = await _authenticated_user(db_session, email="admin@example.com")

    response = await db_async_client.post(
        "/api/v1/users/",
        headers=bearer_headers(token),
        json={
            "email": " Created.User@Example.COM ",
            "display_name": " Created User ",
            "password": "Password123",
        },
    )

    assert response.status_code == 201
    body: dict[str, Any] = response.json()
    assert body["email"] == "created.user@example.com"
    assert body["display_name"] == "Created User"
    assert body["default_workspace_id"] is not None
    assert "password_hash" not in body
    assert "totp_secret_encrypted" not in body


async def test_list_workspaces_route_returns_only_authenticated_user_memberships(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    actor, token = await _authenticated_user(db_session, email="member@example.com")
    visible = build_workspace(slug="visible-workspace", name="Visible Workspace")
    hidden = build_workspace(slug="hidden-workspace", name="Hidden Workspace")
    membership = build_workspace_membership(
        workspace_id=visible.id,
        user_id=actor.id,
        role=WorkspaceRole.READ_ONLY,
    )
    db_session.add_all([visible, hidden, membership])
    await db_session.commit()

    response = await db_async_client.get(
        "/api/v1/workspaces/",
        headers=bearer_headers(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [workspace["slug"] for workspace in body["workspaces"]] == ["visible-workspace"]
    assert body["workspaces"][0]["current_user_role"] == WorkspaceRole.READ_ONLY.value


async def test_create_membership_route_returns_forbidden_for_non_manager(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    actor, token = await _authenticated_user(db_session, email="member@example.com")
    target = build_user(email="target@example.com")
    workspace = build_workspace(slug="team-workspace", name="Team Workspace")
    actor_membership = build_workspace_membership(
        workspace_id=workspace.id,
        user_id=actor.id,
        role=WorkspaceRole.MEMBER,
    )
    db_session.add_all([target, workspace, actor_membership])
    await db_session.commit()

    response = await db_async_client.post(
        f"/api/v1/workspaces/{workspace.id}/memberships",
        headers=bearer_headers(token),
        json={"user_id": str(target.id), "role": WorkspaceRole.ADMIN.value},
    )

    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["detail"] == "Requires higher level role"
    assert body["membership_role"] == WorkspaceRole.MEMBER.value
