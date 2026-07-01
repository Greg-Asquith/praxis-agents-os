# apps/api/tests/services/agent_schedules/test_finalize_execution.py

"""Tests for finalizing scheduled executions."""

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
    mark_run_awaiting_approval,
    start_agent_run,
)
from services.agent_runs.domain import RUN_TRIGGER_SCHEDULED
from services.agent_schedules import finalize_schedule_run_execution
from services.agent_schedules.runs import (
    RUN_STATUS_AWAITING_APPROVAL,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_RUNNING,
    RUN_STATUS_TERMINAL_FAILED,
)
from tests.factories import build_user, build_workspace

pytestmark = pytest.mark.asyncio


async def _prepared_schedule_context(db: AsyncSession, *, schedule_type: str = "once"):
    now = datetime.now(UTC)
    user = build_user(email=f"finalize-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"finalize-{uuid4().hex[:8]}")
    db.add_all([user, workspace])
    await db.flush()

    agent = Agent(
        name="Finalize Agent",
        slug=f"finalize-agent-{uuid4().hex[:8]}",
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
        schedule_type=schedule_type,
        interval_minutes=5 if schedule_type == "interval" else None,
        run_once_at=now - timedelta(minutes=1) if schedule_type == "once" else None,
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
    conversation.schedule_run_id = schedule_run.id

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
    return user, workspace, agent, schedule, conversation, schedule_run, run


async def test_completed_generic_run_retires_once_schedule(db_session: AsyncSession) -> None:
    _user, _workspace, _agent, schedule, _conversation, schedule_run, run = (
        await _prepared_schedule_context(db_session)
    )
    await start_agent_run(db_session, run)
    await complete_agent_run(db_session, run)

    await finalize_schedule_run_execution(
        db_session,
        schedule_run_id=schedule_run.id,
        agent_run_id=run.id,
    )

    assert schedule_run.status == RUN_STATUS_COMPLETED
    assert schedule.is_active is False
    assert schedule.next_run_at is None
    assert schedule.last_run_at is not None


async def test_awaiting_schedule_run_with_completed_generic_run_retires_once_schedule(
    db_session: AsyncSession,
) -> None:
    _user, _workspace, _agent, schedule, _conversation, schedule_run, run = (
        await _prepared_schedule_context(db_session)
    )
    schedule_run.status = RUN_STATUS_AWAITING_APPROVAL
    await start_agent_run(db_session, run)
    await complete_agent_run(db_session, run)

    await finalize_schedule_run_execution(
        db_session,
        schedule_run_id=schedule_run.id,
        agent_run_id=run.id,
    )

    assert schedule_run.status == RUN_STATUS_COMPLETED
    assert schedule.is_active is False
    assert schedule.next_run_at is None
    assert schedule.last_run_at is not None


async def test_awaiting_approval_does_not_advance_schedule(db_session: AsyncSession) -> None:
    _user, _workspace, _agent, schedule, _conversation, schedule_run, run = (
        await _prepared_schedule_context(db_session, schedule_type="interval")
    )
    original_next_run_at = schedule.next_run_at
    await start_agent_run(db_session, run)
    await mark_run_awaiting_approval(db_session, run)

    await finalize_schedule_run_execution(
        db_session,
        schedule_run_id=schedule_run.id,
        agent_run_id=run.id,
    )

    assert schedule_run.status == RUN_STATUS_AWAITING_APPROVAL
    assert schedule.next_run_at == original_next_run_at
    assert schedule.is_active is True


async def test_awaiting_schedule_run_with_awaiting_generic_run_stays_paused(
    db_session: AsyncSession,
) -> None:
    _user, _workspace, _agent, schedule, _conversation, schedule_run, run = (
        await _prepared_schedule_context(db_session, schedule_type="interval")
    )
    original_next_run_at = schedule.next_run_at
    schedule_run.status = RUN_STATUS_AWAITING_APPROVAL
    await start_agent_run(db_session, run)
    await mark_run_awaiting_approval(db_session, run)

    await finalize_schedule_run_execution(
        db_session,
        schedule_run_id=schedule_run.id,
        agent_run_id=run.id,
    )

    assert schedule_run.status == RUN_STATUS_AWAITING_APPROVAL
    assert schedule.next_run_at == original_next_run_at
    assert schedule.is_active is True


async def test_failed_generic_run_terminally_fails_schedule(db_session: AsyncSession) -> None:
    _user, _workspace, _agent, schedule, _conversation, schedule_run, run = (
        await _prepared_schedule_context(db_session)
    )
    await start_agent_run(db_session, run)
    await fail_agent_run(db_session, run, error_code="provider", error_message="boom")

    await finalize_schedule_run_execution(
        db_session,
        schedule_run_id=schedule_run.id,
        agent_run_id=run.id,
    )

    assert schedule_run.status == RUN_STATUS_TERMINAL_FAILED
    assert schedule_run.last_error_code == "provider"
    assert schedule.is_active is False
    assert schedule.next_run_at is None


async def test_awaiting_schedule_run_with_failed_generic_run_terminally_fails_schedule(
    db_session: AsyncSession,
) -> None:
    _user, _workspace, _agent, schedule, _conversation, schedule_run, run = (
        await _prepared_schedule_context(db_session)
    )
    schedule_run.status = RUN_STATUS_AWAITING_APPROVAL
    await start_agent_run(db_session, run)
    await fail_agent_run(db_session, run, error_code="provider", error_message="boom")

    await finalize_schedule_run_execution(
        db_session,
        schedule_run_id=schedule_run.id,
        agent_run_id=run.id,
    )

    assert schedule_run.status == RUN_STATUS_TERMINAL_FAILED
    assert schedule_run.last_error_code == "provider"
    assert schedule.is_active is False
    assert schedule.next_run_at is None


async def test_failed_empty_scheduled_conversation_is_pruned(
    db_session: AsyncSession,
) -> None:
    _user, _workspace, _agent, _schedule, conversation, schedule_run, run = (
        await _prepared_schedule_context(db_session)
    )
    await start_agent_run(db_session, run)
    await fail_agent_run(db_session, run, error_code="provider", error_message="boom")

    await finalize_schedule_run_execution(
        db_session,
        schedule_run_id=schedule_run.id,
        agent_run_id=run.id,
    )

    assert conversation.deleted is True
    assert schedule_run.status == RUN_STATUS_TERMINAL_FAILED
