# apps/api/tests/routes/test_management_routes.py

"""HTTP-boundary tests for key user and workspace management routes."""

import pytest
from httpx2 import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from core.database import set_session_tenant_context
from core.settings import settings
from models.audit_event import AuditEvent
from models.user import User
from models.workspace import WorkspaceRole
from services.audit_events import AuditAction, AuditResourceType
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


@pytest.mark.parametrize(
    ("role", "super_admin", "expected_status"),
    [
        (WorkspaceRole.ADMIN, False, 204),
        (WorkspaceRole.MEMBER, False, 403),
    ],
)
async def test_delete_membership_route_enforces_management_permissions(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    role: WorkspaceRole | None,
    super_admin: bool,
    expected_status: int,
) -> None:
    actor, token = await _authenticated_user(db_session, email="actor@example.com")
    monkeypatch.setattr(settings, "SUPER_ADMIN_EMAILS", actor.email if super_admin else "")
    target = build_user(email="target@example.com")
    workspace = build_workspace(slug="remove-member")
    if role is not None:
        db_session.add(
            build_workspace_membership(workspace_id=workspace.id, user_id=actor.id, role=role)
        )
    target_membership = build_workspace_membership(workspace_id=workspace.id, user_id=target.id)
    db_session.add_all([target, workspace, target_membership])
    await db_session.flush()
    target.default_workspace_id = workspace.id
    await db_session.commit()

    response = await db_async_client.delete(
        f"/api/v1/workspaces/{workspace.id}/memberships/{target_membership.id}",
        headers=bearer_headers(token),
    )

    assert response.status_code == expected_status
    await db_session.refresh(target_membership)
    await db_session.refresh(target)
    removed = expected_status == 204
    assert target_membership.deleted is removed
    assert target.default_workspace_id == (None if removed else workspace.id)
    await set_session_tenant_context(db_session, workspace_id=workspace.id, user_id=actor.id)
    audit_event = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.workspace_id == workspace.id,
            AuditEvent.resource_id == str(target_membership.id),
            AuditEvent.resource_type == AuditResourceType.WORKSPACE_MEMBERSHIP.value,
            AuditEvent.action == AuditAction.DELETE.value,
        )
    )
    if removed:
        assert response.content == b""
        assert target_membership.deleted_by == actor.id
        assert audit_event is not None
        assert audit_event.actor_id == str(actor.id)
        assert audit_event.details["user_id"] == str(target.id)
    else:
        assert audit_event is None


async def test_delete_membership_route_rejects_membership_from_another_workspace(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    actor, token = await _authenticated_user(db_session, email="actor@example.com")
    target = build_user(email="target@example.com")
    workspace = build_workspace(slug="managed-workspace")
    other_workspace = build_workspace(slug="other-workspace")
    actor_membership = build_workspace_membership(
        workspace_id=workspace.id, user_id=actor.id, role=WorkspaceRole.ADMIN
    )
    target_membership = build_workspace_membership(
        workspace_id=other_workspace.id, user_id=target.id
    )
    db_session.add_all([target, workspace, other_workspace, actor_membership, target_membership])
    await db_session.commit()

    response = await db_async_client.delete(
        f"/api/v1/workspaces/{workspace.id}/memberships/{target_membership.id}",
        headers=bearer_headers(token),
    )

    assert response.status_code == 404
    await db_session.refresh(target_membership)
    assert target_membership.deleted is False
