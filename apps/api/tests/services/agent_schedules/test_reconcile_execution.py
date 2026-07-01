# apps/api/tests/services/agent_schedules/test_reconcile_execution.py

"""Tests for reconciling abandoned scheduled executions."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent, AgentSchedule, AgentScheduleRun
from models.conversation import Conversation
from services.agent_runs import (
    complete_agent_run,
    create_agent_run,
    fail_agent_run,
    start_agent_run,
)
from services.agent_runs.domain import RUN_TRIGGER_SCHEDULED
from services.agent_schedules import reconcile_schedule_run_execution
from services.agent_schedules.runs import (
    RUN_STATUS_ACCEPTED,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_RETRYABLE_FAILED,
    RUN_STATUS_RUNNING,
    RUN_STATUS_TERMINAL_FAILED,
)
from tests.factories import build_user, build_workspace

pytestmark = pytest.mark.asyncio


async def _running_schedule_with_run(db: AsyncSession):
    now = datetime.now(UTC)
    user = build_user(email=f"reconcile-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"reconcile-{uuid4().hex[:8]}")
    db.add_all([user, workspace])
    await db.flush()

    agent = Agent(
        name="Reconcile Agent",
        slug=f"reconcile-agent-{uuid4().hex[:8]}",
        instructions="Reply plainly.",
        workspace_id=workspace.id,
        created_by=user.id,
    )
    db.add(agent)
    await db.flush()

    schedule = AgentSchedule(
        agent_id=agent.id,
        user_id=user.id,
        workspace_id=workspace.id,
        schedule_type="once",
        run_once_at=now - timedelta(minutes=1),
        next_run_at=now - timedelta(minutes=1),
        default_prompt="Run scheduled work",
    )
    db.add(schedule)
    await db.flush()

    conversation = Conversation(
        user_id=user.id,
        workspace_id=workspace.id,
        created_by=user.id,
        source="scheduled",
        schedule_id=schedule.id,
        active_agent_id=agent.id,
    )
    db.add(conversation)
    await db.flush()

    schedule_run = AgentScheduleRun(
        schedule_id=schedule.id,
        workspace_id=workspace.id,
        user_id=user.id,
        agent_id=agent.id,
        conversation_id=conversation.id,
        scheduled_for=schedule.next_run_at,
        status=RUN_STATUS_RUNNING,
        attempt_count=1,
    )
    db.add(schedule_run)
    await db.flush()

    run = await create_agent_run(
        db,
        conversation_id=conversation.id,
        agent_id=agent.id,
        workspace_id=workspace.id,
        user_id=user.id,
        trigger=RUN_TRIGGER_SCHEDULED,
    )
    schedule_run.agent_run_id = run.id
    await db.flush()
    return schedule, schedule_run, run


async def test_reconcile_running_schedule_with_failed_generic_run(
    db_session: AsyncSession,
) -> None:
    schedule, schedule_run, run = await _running_schedule_with_run(db_session)
    await start_agent_run(db_session, run)
    await fail_agent_run(db_session, run, error_code="abandoned", error_message="stale")

    reconciled = await reconcile_schedule_run_execution(db_session)

    assert reconciled == 1
    assert schedule_run.status == RUN_STATUS_TERMINAL_FAILED
    assert schedule.is_active is False


async def test_reconcile_running_schedule_with_completed_generic_run(
    db_session: AsyncSession,
) -> None:
    schedule, schedule_run, run = await _running_schedule_with_run(db_session)
    await start_agent_run(db_session, run)
    await complete_agent_run(db_session, run)

    reconciled = await reconcile_schedule_run_execution(db_session)

    assert reconciled == 1
    assert schedule_run.status == RUN_STATUS_COMPLETED
    assert schedule.is_active is False


async def test_reconcile_expired_accepted_run_without_generic_run(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    user = build_user(email=f"reconcile-stale-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"reconcile-stale-{uuid4().hex[:8]}")
    db_session.add_all([user, workspace])
    await db_session.flush()
    agent = Agent(
        name="Reconcile Stale Agent",
        slug=f"reconcile-stale-agent-{uuid4().hex[:8]}",
        instructions="Reply plainly.",
        workspace_id=workspace.id,
        created_by=user.id,
    )
    db_session.add(agent)
    await db_session.flush()
    schedule = AgentSchedule(
        agent_id=agent.id,
        user_id=user.id,
        workspace_id=workspace.id,
        schedule_type="once",
        run_once_at=now - timedelta(minutes=1),
        next_run_at=now - timedelta(minutes=1),
        default_prompt="Run scheduled work",
    )
    db_session.add(schedule)
    await db_session.flush()
    schedule_run = AgentScheduleRun(
        schedule_id=schedule.id,
        workspace_id=workspace.id,
        user_id=user.id,
        agent_id=agent.id,
        scheduled_for=schedule.next_run_at,
        status=RUN_STATUS_ACCEPTED,
        accepted_at=now - timedelta(minutes=10),
        attempt_count=1,
    )
    db_session.add(schedule_run)
    await db_session.flush()

    reconciled = await reconcile_schedule_run_execution(db_session, now=now)

    assert reconciled == 1
    assert schedule_run.status == RUN_STATUS_RETRYABLE_FAILED
    assert schedule_run.last_error_code == "schedule_execution_abandoned"
