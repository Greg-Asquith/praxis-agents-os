# apps/api/tests/services/users/test_user_management_services.py

"""Focused tests for high-risk user-management service behavior."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from core.database import get_maintenance_async_db_session_factory
from core.exceptions.general import AppValidationError
from models.agent import Agent, AgentSchedule, AgentScheduleRun
from models.audit_event import AuditEvent
from models.session import Session
from models.user import User, UserAuth
from models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from services.agent_schedules import prepare_schedule_run_execution
from services.agent_schedules.domain import RUN_STATUS_CLAIMED, RUN_STATUS_TERMINAL_FAILED
from services.audit_events import AuditAction, AuditResourceType
from services.users import create_user, delete_user, update_user
from services.users.schemas import UserCreateRequest, UserUpdateRequest
from services.workspaces.utils import get_active_membership
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.requests import build_test_request

pytestmark = pytest.mark.asyncio


async def _owner_with_claimed_schedule_run(
    db: AsyncSession, user: User
) -> tuple[WorkspaceMembership, AgentSchedule, AgentScheduleRun]:
    """Give the user a team workspace and a schedule whose due run a worker already claimed."""
    workspace = build_workspace(slug=f"owner-{user.id.hex[:8]}")
    membership = build_workspace_membership(
        workspace_id=workspace.id, user_id=user.id, role=WorkspaceRole.OWNER
    )
    db.add_all([workspace, membership])
    await db.flush()
    agent = Agent(
        name="Schedule Agent",
        slug=f"schedule-agent-{user.id.hex[:8]}",
        instructions="Reply plainly.",
        workspace_id=workspace.id,
        created_by=user.id,
    )
    db.add(agent)
    await db.flush()
    due = datetime.now(UTC) - timedelta(minutes=1)
    schedule = AgentSchedule(
        agent_id=agent.id,
        user_id=user.id,
        workspace_id=workspace.id,
        schedule_type="interval",
        interval_minutes=60,
        next_run_at=due,
        default_prompt="Send the report",
    )
    db.add(schedule)
    await db.flush()
    schedule_run = AgentScheduleRun(
        schedule_id=schedule.id,
        workspace_id=workspace.id,
        user_id=user.id,
        agent_id=agent.id,
        scheduled_for=due,
        status=RUN_STATUS_CLAIMED,
        attempt_count=1,
    )
    db.add(schedule_run)
    await db.flush()
    return membership, schedule, schedule_run


async def test_create_user_provisions_personal_workspace_and_records_audit(
    db_session: AsyncSession,
) -> None:
    actor = build_user(email="admin@example.com", display_name="Admin")
    strong_password = "Password123"
    db_session.add(actor)
    await db_session.flush()

    result = await create_user(
        db_session,
        request=build_test_request(path="/api/v1/users/"),
        actor=actor,
        payload=UserCreateRequest(
            email=" New.User@Example.COM ",
            display_name=" New User ",
            password=strong_password,
        ),
    )

    user = await db_session.get(User, result.id)
    assert user is not None
    assert result.email == "new.user@example.com"
    assert result.display_name == "New User"
    assert user.verify_password(strong_password)
    assert user.default_workspace_id is not None

    workspace = await db_session.get(Workspace, user.default_workspace_id)
    assert workspace is not None
    assert workspace.is_personal is True
    assert workspace.name == "My Workspace"

    membership = await db_session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.user_id == user.id,
            WorkspaceMembership.deleted.is_(False),
        )
    )
    assert membership is not None
    assert membership.role == WorkspaceRole.OWNER.value

    audit_event = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == AuditAction.CREATE.value,
            AuditEvent.resource_type == AuditResourceType.USER.value,
            AuditEvent.resource_id == str(user.id),
        )
    )
    assert audit_event is not None
    assert audit_event.workspace_id == workspace.id
    assert audit_event.actor_user_id == actor.id
    assert audit_event.details["source"] == "admin"


async def test_update_user_deactivation_stops_runs_and_reactivation_keeps_schedules_off(
    db_session: AsyncSession,
) -> None:
    actor = build_user(email="admin@example.com")
    target = build_user(email="target@example.com")
    db_session.add_all([actor, target])
    await db_session.flush()
    membership, schedule, schedule_run = await _owner_with_claimed_schedule_run(db_session, target)
    session_result = await session_manager.create_session(db_session, str(target.id))

    result = await update_user(
        db_session,
        request=build_test_request(path=f"/api/v1/users/{target.id}", method="PATCH"),
        actor=actor,
        user_id=target.id,
        payload=UserUpdateRequest(is_active=False),
    )

    session = await db_session.get(Session, UUID(session_result["session_id"]))
    assert result.is_active is False
    assert session is not None
    assert session.deleted is True
    await db_session.refresh(schedule)
    assert schedule.is_active is False
    assert schedule.next_run_at is None

    # The membership survives deactivation, but the run claimed beforehand is still refused.
    await db_session.refresh(membership)
    assert membership.deleted is False
    prepared = await prepare_schedule_run_execution(db_session, schedule_run_id=schedule_run.id)
    assert prepared.should_execute is False
    assert schedule_run.status == RUN_STATUS_TERMINAL_FAILED

    # User audit rows have no workspace, so RLS hides them from the tenant-scoped session.
    async with get_maintenance_async_db_session_factory()() as maintenance_db:
        audit_event = await maintenance_db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == AuditAction.UPDATE.value,
                AuditEvent.resource_type == AuditResourceType.USER.value,
                AuditEvent.resource_id == str(target.id),
            )
        )
    assert audit_event is not None
    assert audit_event.details == {
        "fields": ["is_active"],
        "revoked_sessions": 1,
        "disabled_schedules": 1,
    }

    await update_user(
        db_session,
        request=build_test_request(path=f"/api/v1/users/{target.id}", method="PATCH"),
        actor=actor,
        user_id=target.id,
        payload=UserUpdateRequest(is_active=True),
    )
    restored = await get_active_membership(
        db_session, workspace_id=membership.workspace_id, user_id=target.id
    )
    assert restored is not None
    await db_session.refresh(schedule)
    assert schedule.is_active is False


async def test_delete_user_ends_memberships_sign_ins_and_schedules(
    db_session: AsyncSession,
) -> None:
    actor = build_user(email="admin@example.com")
    target = build_user(email="target@example.com")
    db_session.add_all([actor, target])
    await db_session.flush()
    membership, schedule, schedule_run = await _owner_with_claimed_schedule_run(db_session, target)
    auth = UserAuth(
        user_id=target.id,
        provider="google",
        provider_user_id="google-deleted-user",
        email=target.email,
        email_verified=True,
    )
    db_session.add(auth)
    await db_session.flush()

    await delete_user(
        db_session,
        request=build_test_request(path=f"/api/v1/users/{target.id}", method="DELETE"),
        actor=actor,
        user_id=target.id,
    )

    for row in (membership, auth, schedule):
        await db_session.refresh(row)
    assert membership.deleted is True
    assert auth.deleted is True
    assert schedule.is_active is False
    prepared = await prepare_schedule_run_execution(db_session, schedule_run_id=schedule_run.id)
    assert prepared.should_execute is False
    assert schedule_run.last_error_code == "workspace_membership_revoked"

    disable_event = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == AuditAction.DISABLE.value,
            AuditEvent.resource_id == str(schedule.id),
        )
    )
    assert disable_event is not None
    assert disable_event.details["reason"] == "user_deleted"


async def test_delete_user_rejects_self_deletion(db_session: AsyncSession) -> None:
    actor = build_user(email="admin@example.com")
    db_session.add(actor)
    await db_session.flush()

    with pytest.raises(AppValidationError, match="cannot delete your own user account"):
        await delete_user(
            db_session,
            request=build_test_request(path=f"/api/v1/users/{actor.id}", method="DELETE"),
            actor=actor,
            user_id=actor.id,
        )

    assert actor.deleted is False
    assert actor.is_active is True
