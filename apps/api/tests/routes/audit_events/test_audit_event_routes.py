# apps/api/tests/routes/audit_events/test_audit_event_routes.py

"""HTTP-boundary tests for workspace audit-event routes."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx2 import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from models.audit_event import AuditEvent
from models.user import User
from models.workspace import Workspace, WorkspaceRole
from services.audit_events import AuditAction, AuditActorType, AuditResourceType, AuditStatus
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.auth import bearer_headers

pytestmark = pytest.mark.asyncio


async def _authenticated_workspace(
    db: AsyncSession,
    *,
    role: WorkspaceRole = WorkspaceRole.OWNER,
    workspace: Workspace | None = None,
) -> tuple[User, Workspace, dict[str, str]]:
    user = build_user(email=f"audit-{uuid4().hex}@example.com")
    workspace = workspace or build_workspace(slug=f"audit-{uuid4().hex[:8]}")
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


async def _seed_audit_event(
    db: AsyncSession,
    *,
    workspace: Workspace | None,
    actor: User | None,
    action: AuditAction = AuditAction.CREATE,
    resource_type: AuditResourceType | str = AuditResourceType.AGENT,
    resource_id: str | None = None,
    status: AuditStatus = AuditStatus.SUCCESS,
    occurred_at: datetime | None = None,
    details: dict[str, object] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        workspace_id=workspace.id if workspace else None,
        occurred_at=occurred_at or datetime.now(UTC),
        action=action.value,
        resource_type=resource_type.value
        if isinstance(resource_type, AuditResourceType)
        else resource_type,
        resource_id=resource_id or str(uuid4()),
        status=status.value,
        summary=f"{action.value} audit event",
        actor_type=AuditActorType.USER.value if actor else AuditActorType.SYSTEM.value,
        actor_id=str(actor.id) if actor else None,
        actor_user_id=actor.id if actor else None,
        actor_display=actor.email if actor else "System",
        requested_by_user_id=actor.id if actor else None,
        details=details or {"seed": True},
        request_id=f"req-{uuid4().hex[:8]}",
        ip_address="127.0.0.1",
        user_agent="pytest",
    )
    db.add(event)
    await db.flush()
    return event


async def test_audit_event_list_authorization_matrix(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    owner, workspace, owner_headers = await _authenticated_workspace(db_session)
    _admin, _workspace, admin_headers = await _authenticated_workspace(
        db_session,
        role=WorkspaceRole.ADMIN,
        workspace=workspace,
    )
    _member, _workspace, member_headers = await _authenticated_workspace(
        db_session,
        role=WorkspaceRole.MEMBER,
        workspace=workspace,
    )
    _read_only, _workspace, read_only_headers = await _authenticated_workspace(
        db_session,
        role=WorkspaceRole.READ_ONLY,
        workspace=workspace,
    )
    await _seed_audit_event(db_session, workspace=workspace, actor=owner)
    await db_session.commit()

    owner_response = await db_async_client.get("/api/v1/audit-events/", headers=owner_headers)
    assert owner_response.status_code == 200
    assert owner_response.json()["total"] == 1

    admin_response = await db_async_client.get("/api/v1/audit-events/", headers=admin_headers)
    assert admin_response.status_code == 200
    assert admin_response.json()["total"] == 1

    member_response = await db_async_client.get("/api/v1/audit-events/", headers=member_headers)
    assert member_response.status_code == 403
    assert member_response.headers["content-type"].startswith("application/problem+json")

    read_only_response = await db_async_client.get(
        "/api/v1/audit-events/",
        headers=read_only_headers,
    )
    assert read_only_response.status_code == 403
    assert read_only_response.headers["content-type"].startswith("application/problem+json")

    unauthenticated_response = await db_async_client.get("/api/v1/audit-events/")
    assert unauthenticated_response.status_code == 401
    assert unauthenticated_response.headers["content-type"].startswith("application/problem+json")


async def test_audit_event_list_is_workspace_scoped(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace_a, headers = await _authenticated_workspace(db_session)
    workspace_b = build_workspace(slug=f"audit-other-{uuid4().hex[:8]}")
    db_session.add(workspace_b)
    await db_session.flush()
    visible = await _seed_audit_event(
        db_session,
        workspace=workspace_a,
        actor=user,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.AGENT,
        resource_id="same-shaped-resource",
    )
    hidden = await _seed_audit_event(
        db_session,
        workspace=workspace_b,
        actor=user,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.AGENT,
        resource_id="same-shaped-resource",
    )
    await db_session.commit()

    response = await db_async_client.get("/api/v1/audit-events/", headers=headers)

    assert response.status_code == 200
    event_ids = {event["id"] for event in response.json()["events"]}
    assert str(visible.id) in event_ids
    assert str(hidden.id) not in event_ids


async def test_audit_event_filters_narrow_results(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    actor, workspace, headers = await _authenticated_workspace(db_session)
    other_actor = build_user(email=f"audit-other-actor-{uuid4().hex}@example.com")
    db_session.add(other_actor)
    await db_session.flush()
    base_time = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    matching = await _seed_audit_event(
        db_session,
        workspace=workspace,
        actor=actor,
        action=AuditAction.DELETE,
        resource_type=AuditResourceType.AGENT_SCHEDULE,
        resource_id="schedule-1",
        status=AuditStatus.DENIED,
        occurred_at=base_time,
    )
    await _seed_audit_event(
        db_session,
        workspace=workspace,
        actor=other_actor,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.AGENT,
        resource_id="agent-1",
        status=AuditStatus.SUCCESS,
        occurred_at=base_time - timedelta(days=3),
    )
    await _seed_audit_event(
        db_session,
        workspace=workspace,
        actor=actor,
        action=AuditAction.DELETE,
        resource_type=AuditResourceType.AGENT_SCHEDULE,
        resource_id="schedule-2",
        status=AuditStatus.DENIED,
        occurred_at=base_time + timedelta(days=3),
    )
    await db_session.commit()

    response = await db_async_client.get(
        "/api/v1/audit-events/",
        headers=headers,
        params={
            "action": "delete",
            "resource_type": "agent_schedule",
            "status": "denied",
            "actor_user_id": str(actor.id),
            "occurred_after": (base_time - timedelta(hours=1)).isoformat(),
            "occurred_before": (base_time + timedelta(hours=1)).isoformat(),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["events"][0]["id"] == str(matching.id)


async def test_audit_event_filter_rejects_unknown_action(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    _user, _workspace, headers = await _authenticated_workspace(db_session)

    response = await db_async_client.get(
        "/api/v1/audit-events/",
        headers=headers,
        params={"action": "typo"},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["field"] == "action"
    assert "create" in body["allowed_values"]


async def test_audit_event_detail_scoping_and_system_visibility(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace_a, headers = await _authenticated_workspace(db_session)
    workspace_b = build_workspace(slug=f"audit-detail-other-{uuid4().hex[:8]}")
    db_session.add(workspace_b)
    await db_session.flush()
    visible = await _seed_audit_event(
        db_session,
        workspace=workspace_a,
        actor=user,
        details={"field": "value"},
    )
    hidden = await _seed_audit_event(db_session, workspace=workspace_b, actor=user)
    system_event = await _seed_audit_event(db_session, workspace=None, actor=None)
    await db_session.commit()

    detail_response = await db_async_client.get(
        f"/api/v1/audit-events/{visible.id}",
        headers=headers,
    )
    assert detail_response.status_code == 200
    assert detail_response.json()["details"] == {"field": "value"}

    cross_workspace_response = await db_async_client.get(
        f"/api/v1/audit-events/{hidden.id}",
        headers=headers,
    )
    assert cross_workspace_response.status_code == 404

    system_detail_response = await db_async_client.get(
        f"/api/v1/audit-events/{system_event.id}",
        headers=headers,
    )
    assert system_detail_response.status_code == 404

    list_response = await db_async_client.get("/api/v1/audit-events/", headers=headers)
    assert str(system_event.id) not in {event["id"] for event in list_response.json()["events"]}
