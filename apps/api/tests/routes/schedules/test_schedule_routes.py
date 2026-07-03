# apps/api/tests/routes/schedules/test_schedule_routes.py

"""HTTP-boundary tests for workspace agent schedule routes."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.sessions import session_manager
from models.agent import Agent, AgentSchedule, AgentScheduleRun
from models.agent_run import AgentRun
from models.audit_event import AuditEvent
from models.conversation import Conversation
from models.user import User
from models.workspace import Workspace, WorkspaceRole
from services.agent_runs.domain import RUN_TRIGGER_SCHEDULED
from services.agent_schedules.runs import (
    RUN_STATUS_AWAITING_APPROVAL,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_RETRYABLE_FAILED,
)
from services.audit_events import AuditAction, AuditResourceType
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.auth import bearer_headers

pytestmark = pytest.mark.asyncio


async def _authenticated_workspace(
    db: AsyncSession,
    *,
    role: WorkspaceRole = WorkspaceRole.OWNER,
    workspace: Workspace | None = None,
) -> tuple[User, Workspace, dict[str, str]]:
    user = build_user(email=f"schedule-{uuid4().hex}@example.com")
    workspace = workspace or build_workspace(slug=f"schedules-{uuid4().hex[:8]}")
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


async def _create_agent(
    db: AsyncSession,
    *,
    workspace: Workspace,
    user: User,
    is_active: bool = True,
) -> Agent:
    agent = Agent(
        name="Schedule Agent",
        slug=f"schedule-agent-{uuid4().hex[:8]}",
        instructions="Run scheduled work.",
        workspace_id=workspace.id,
        created_by=user.id,
        model_provider="openai",
        model="gpt-5.4-mini",
        is_active=is_active,
    )
    db.add(agent)
    await db.flush()
    return agent


async def _create_schedule(
    db: AsyncSession,
    *,
    workspace: Workspace,
    user: User,
    agent: Agent,
    is_active: bool = True,
    schedule_type: str = "interval",
    next_run_at: datetime | None = None,
    run_once_at: datetime | None = None,
) -> AgentSchedule:
    now = datetime.now(UTC)
    schedule = AgentSchedule(
        agent_id=agent.id,
        user_id=user.id,
        workspace_id=workspace.id,
        schedule_type=schedule_type,
        cron_expression="*/15 * * * *" if schedule_type == "cron" else None,
        interval_minutes=15 if schedule_type == "interval" else None,
        run_once_at=run_once_at,
        timezone="UTC",
        default_prompt="Run the scheduled task",
        is_active=is_active,
        next_run_at=next_run_at or now + timedelta(minutes=15),
    )
    db.add(schedule)
    await db.flush()
    return schedule


async def test_create_cron_schedule_persists_read_shape_and_audit(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, headers = await _authenticated_workspace(db_session)
    agent = await _create_agent(db_session, workspace=workspace, user=user)
    await db_session.commit()

    response = await db_async_client.post(
        "/api/v1/schedules/",
        headers=headers,
        json={
            "agent_id": str(agent.id),
            "schedule_type": "cron",
            "cron_expression": "*/5 * * * *",
            "timezone": "UTC",
            "default_prompt": "  Check account performance.  ",
            "execution_params": {"temperature": 0},
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["agent_id"] == str(agent.id)
    assert body["workspace_id"] == str(workspace.id)
    assert body["user_id"] == str(user.id)
    assert body["schedule_type"] == "cron"
    assert body["cron_expression"] == "*/5 * * * *"
    assert body["default_prompt"] == "Check account performance."
    assert body["execution_params"] == {"temperature": 0}
    assert body["is_active"] is True
    assert body["next_run_at"] is not None
    assert body["health"] == "healthy"
    assert body["latest_run"] is None
    assert "active_context" not in body

    audit_event = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == AuditAction.CREATE.value,
            AuditEvent.resource_type == AuditResourceType.AGENT_SCHEDULE.value,
            AuditEvent.resource_id == body["id"],
        )
    )
    assert audit_event is not None
    assert audit_event.details["agent_id"] == str(agent.id)
    assert audit_event.details["schedule_type"] == "cron"


@pytest.mark.parametrize(
    "payload",
    [
        {"schedule_type": "cron", "cron_expression": "not cron"},
        {"schedule_type": "interval", "interval_minutes": 0},
        {
            "schedule_type": "once",
            "run_once_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        },
        {"schedule_type": "interval", "interval_minutes": 15, "default_prompt": "   "},
    ],
)
async def test_create_schedule_rejects_invalid_payloads(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    payload: dict[str, object],
) -> None:
    user, workspace, headers = await _authenticated_workspace(db_session)
    agent = await _create_agent(db_session, workspace=workspace, user=user)
    await db_session.commit()

    request_body = {
        "agent_id": str(agent.id),
        "schedule_type": "interval",
        "interval_minutes": 15,
        "default_prompt": "Run this.",
    }
    request_body.update(payload)

    response = await db_async_client.post(
        "/api/v1/schedules/",
        headers=headers,
        json=request_body,
    )

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_create_schedule_rejects_cross_workspace_agent(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, _workspace, headers = await _authenticated_workspace(db_session)
    other_workspace = build_workspace(slug=f"other-schedules-{uuid4().hex[:8]}")
    db_session.add(other_workspace)
    await db_session.flush()
    other_agent = await _create_agent(db_session, workspace=other_workspace, user=user)
    await db_session.commit()

    response = await db_async_client.post(
        "/api/v1/schedules/",
        headers=headers,
        json={
            "agent_id": str(other_agent.id),
            "schedule_type": "interval",
            "interval_minutes": 15,
            "default_prompt": "Run this.",
        },
    )

    assert response.status_code == 400
    assert response.json()["field"] == "agent_id"


async def test_schedule_mutation_authorization_matrix(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    owner, workspace, owner_headers = await _authenticated_workspace(db_session)
    member, _workspace, member_headers = await _authenticated_workspace(
        db_session,
        role=WorkspaceRole.MEMBER,
        workspace=workspace,
    )
    admin, _workspace, admin_headers = await _authenticated_workspace(
        db_session,
        role=WorkspaceRole.ADMIN,
        workspace=workspace,
    )
    _read_only, _workspace, read_only_headers = await _authenticated_workspace(
        db_session,
        role=WorkspaceRole.READ_ONLY,
        workspace=workspace,
    )
    agent = await _create_agent(db_session, workspace=workspace, user=owner)
    schedule = await _create_schedule(db_session, workspace=workspace, user=owner, agent=agent)
    await db_session.commit()

    blocked_create = await db_async_client.post(
        "/api/v1/schedules/",
        headers=read_only_headers,
        json={
            "agent_id": str(agent.id),
            "schedule_type": "interval",
            "interval_minutes": 15,
            "default_prompt": "Blocked.",
        },
    )
    assert blocked_create.status_code == 403

    member_update = await db_async_client.patch(
        f"/api/v1/schedules/{schedule.id}",
        headers=member_headers,
        json={"default_prompt": "Member should not mutate."},
    )
    assert member.id != owner.id
    assert member_update.status_code == 403

    admin_update = await db_async_client.patch(
        f"/api/v1/schedules/{schedule.id}",
        headers=admin_headers,
        json={"default_prompt": "Admin can mutate."},
    )
    assert admin.id != owner.id
    assert admin_update.status_code == 200
    assert admin_update.json()["default_prompt"] == "Admin can mutate."

    owner_delete = await db_async_client.delete(
        f"/api/v1/schedules/{schedule.id}",
        headers=owner_headers,
    )
    assert owner_delete.status_code == 204

    audit_actions = set(
        await db_session.scalars(
            select(AuditEvent.action).where(
                AuditEvent.resource_type == AuditResourceType.AGENT_SCHEDULE.value,
                AuditEvent.resource_id == str(schedule.id),
            )
        )
    )
    assert {AuditAction.UPDATE.value, AuditAction.DELETE.value} <= audit_actions


async def test_list_schedules_filters_and_includes_latest_run_health(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, headers = await _authenticated_workspace(db_session)
    agent = await _create_agent(db_session, workspace=workspace, user=user)
    other_agent = await _create_agent(db_session, workspace=workspace, user=user)
    active = await _create_schedule(db_session, workspace=workspace, user=user, agent=agent)
    inactive = await _create_schedule(
        db_session,
        workspace=workspace,
        user=user,
        agent=agent,
        is_active=False,
    )
    deleted = await _create_schedule(db_session, workspace=workspace, user=user, agent=agent)
    deleted.soft_delete(deleted_by=user.id, cascade=False)
    other_agent_schedule = await _create_schedule(
        db_session,
        workspace=workspace,
        user=user,
        agent=other_agent,
    )
    run = AgentScheduleRun(
        schedule_id=active.id,
        workspace_id=workspace.id,
        user_id=user.id,
        agent_id=agent.id,
        scheduled_for=datetime.now(UTC),
        status=RUN_STATUS_RETRYABLE_FAILED,
        attempt_count=1,
    )
    db_session.add(run)
    await db_session.commit()

    response = await db_async_client.get("/api/v1/schedules/", headers=headers)

    assert response.status_code == 200
    body = response.json()
    ids = {item["id"] for item in body["items"]}
    assert str(active.id) in ids
    assert str(other_agent_schedule.id) in ids
    assert str(inactive.id) not in ids
    assert str(deleted.id) not in ids
    active_item = next(item for item in body["items"] if item["id"] == str(active.id))
    assert active_item["health"] == "retrying"
    assert active_item["latest_run"]["status"] == RUN_STATUS_RETRYABLE_FAILED

    include_inactive = await db_async_client.get(
        "/api/v1/schedules/?include_inactive=true",
        headers=headers,
    )
    include_ids = {item["id"] for item in include_inactive.json()["items"]}
    assert str(inactive.id) in include_ids
    assert str(deleted.id) not in include_ids

    filtered = await db_async_client.get(
        f"/api/v1/schedules/?agent_id={agent.id}&include_inactive=true",
        headers=headers,
    )
    assert {item["id"] for item in filtered.json()["items"]} == {
        str(active.id),
        str(inactive.id),
    }


async def test_pause_enable_and_expired_once_enable(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, headers = await _authenticated_workspace(db_session)
    agent = await _create_agent(db_session, workspace=workspace, user=user)
    schedule = await _create_schedule(db_session, workspace=workspace, user=user, agent=agent)
    expired_once = await _create_schedule(
        db_session,
        workspace=workspace,
        user=user,
        agent=agent,
        is_active=False,
        schedule_type="once",
        run_once_at=datetime.now(UTC) - timedelta(minutes=10),
        next_run_at=datetime.now(UTC) - timedelta(minutes=10),
    )
    await db_session.commit()

    pause_response = await db_async_client.post(
        f"/api/v1/schedules/{schedule.id}/pause",
        headers=headers,
    )
    assert pause_response.status_code == 200
    assert pause_response.json()["is_active"] is False

    enable_response = await db_async_client.post(
        f"/api/v1/schedules/{schedule.id}/enable",
        headers=headers,
    )
    assert enable_response.status_code == 200
    assert enable_response.json()["is_active"] is True
    assert enable_response.json()["next_run_at"] is not None

    expired_response = await db_async_client.post(
        f"/api/v1/schedules/{expired_once.id}/enable",
        headers=headers,
    )
    assert expired_response.status_code == 400
    assert expired_response.json()["field"] == "run_once_at"

    audit_actions = set(
        await db_session.scalars(
            select(AuditEvent.action).where(
                AuditEvent.resource_type == AuditResourceType.AGENT_SCHEDULE.value,
                AuditEvent.resource_id == str(schedule.id),
            )
        )
    )
    assert {AuditAction.DISABLE.value, AuditAction.ENABLE.value} <= audit_actions


async def test_run_now_requires_active_schedule_and_audits_execute(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, headers = await _authenticated_workspace(db_session)
    agent = await _create_agent(db_session, workspace=workspace, user=user)
    schedule = await _create_schedule(db_session, workspace=workspace, user=user, agent=agent)
    paused = await _create_schedule(
        db_session,
        workspace=workspace,
        user=user,
        agent=agent,
        is_active=False,
    )
    await db_session.commit()

    response = await db_async_client.post(
        f"/api/v1/schedules/{schedule.id}/run-now",
        headers=headers,
    )

    assert response.status_code == 202
    next_run_at = datetime.fromisoformat(response.json()["next_run_at"])
    assert next_run_at <= datetime.now(UTC)

    paused_response = await db_async_client.post(
        f"/api/v1/schedules/{paused.id}/run-now",
        headers=headers,
    )
    assert paused_response.status_code == 409

    audit_event = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.action == AuditAction.EXECUTE.value,
            AuditEvent.resource_type == AuditResourceType.AGENT_SCHEDULE.value,
            AuditEvent.resource_id == str(schedule.id),
        )
    )
    assert audit_event is not None
    assert "requested_at" in audit_event.details


async def test_schedule_run_history_exposes_approval_links_and_filters(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    user, workspace, headers = await _authenticated_workspace(db_session)
    agent = await _create_agent(db_session, workspace=workspace, user=user)
    schedule = await _create_schedule(db_session, workspace=workspace, user=user, agent=agent)
    conversation = Conversation(
        user_id=user.id,
        workspace_id=workspace.id,
        created_by=user.id,
        source="scheduled",
        schedule_id=schedule.id,
        active_agent_id=agent.id,
    )
    db_session.add(conversation)
    await db_session.flush()
    agent_run = AgentRun(
        conversation_id=conversation.id,
        agent_id=agent.id,
        workspace_id=workspace.id,
        user_id=user.id,
        trigger=RUN_TRIGGER_SCHEDULED,
        status="awaiting_approval",
    )
    db_session.add(agent_run)
    await db_session.flush()
    awaiting = AgentScheduleRun(
        schedule_id=schedule.id,
        workspace_id=workspace.id,
        user_id=user.id,
        agent_id=agent.id,
        conversation_id=conversation.id,
        agent_run_id=agent_run.id,
        scheduled_for=datetime.now(UTC),
        status=RUN_STATUS_AWAITING_APPROVAL,
        attempt_count=1,
    )
    completed = AgentScheduleRun(
        schedule_id=schedule.id,
        workspace_id=workspace.id,
        user_id=user.id,
        agent_id=agent.id,
        scheduled_for=datetime.now(UTC) - timedelta(minutes=5),
        status=RUN_STATUS_COMPLETED,
        attempt_count=1,
    )
    db_session.add_all([awaiting, completed])
    await db_session.commit()

    response = await db_async_client.get(
        f"/api/v1/schedules/{schedule.id}/runs",
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    awaiting_item = next(
        item for item in body["items"] if item["status"] == RUN_STATUS_AWAITING_APPROVAL
    )
    assert awaiting_item["conversation_id"] == str(conversation.id)
    assert awaiting_item["agent_run_id"] == str(agent_run.id)

    filtered = await db_async_client.get(
        f"/api/v1/schedules/{schedule.id}/runs?status={RUN_STATUS_AWAITING_APPROVAL}",
        headers=headers,
    )
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["status"] == RUN_STATUS_AWAITING_APPROVAL

    invalid_status = await db_async_client.get(
        f"/api/v1/schedules/{schedule.id}/runs?status=unknown",
        headers=headers,
    )
    assert invalid_status.status_code == 400

    other_workspace = build_workspace(slug=f"runs-other-{uuid4().hex[:8]}")
    db_session.add(other_workspace)
    await db_session.flush()
    other_agent = await _create_agent(db_session, workspace=other_workspace, user=user)
    other_schedule = await _create_schedule(
        db_session,
        workspace=other_workspace,
        user=user,
        agent=other_agent,
    )
    await db_session.commit()

    other_response = await db_async_client.get(
        f"/api/v1/schedules/{other_schedule.id}/runs",
        headers=headers,
    )
    assert other_response.status_code == 404


async def test_preview_schedule_validates_and_returns_future_runs(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
) -> None:
    _user, _workspace, headers = await _authenticated_workspace(db_session)

    response = await db_async_client.post(
        "/api/v1/schedules/preview",
        headers=headers,
        json={
            "schedule_type": "cron",
            "cron_expression": "*/10 * * * *",
            "timezone": "UTC",
            "preview_count": 3,
        },
    )

    assert response.status_code == 200
    next_runs = response.json()["next_runs"]
    assert len(next_runs) == 3
    parsed = [datetime.fromisoformat(value) for value in next_runs]
    assert parsed == sorted(parsed)

    invalid_timezone = await db_async_client.post(
        "/api/v1/schedules/preview",
        headers=headers,
        json={
            "schedule_type": "cron",
            "cron_expression": "*/10 * * * *",
            "timezone": "Mars/Base",
        },
    )
    assert invalid_timezone.status_code == 400
    assert invalid_timezone.json()["field"] == "timezone"
