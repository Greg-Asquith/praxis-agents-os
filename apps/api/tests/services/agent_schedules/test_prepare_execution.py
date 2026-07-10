# apps/api/tests/services/agent_schedules/test_prepare_execution.py

"""Tests for preparing claimed schedule runs."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from core.settings import settings
from models.agent import Agent, AgentSchedule, AgentScheduleRun
from models.agent_run import AgentRun
from models.audit_event import AuditEvent
from models.conversation import Conversation
from services.agent_runs.domain import RUN_TRIGGER_SCHEDULED
from services.agent_schedules import prepare_schedule_run_execution
from services.agent_schedules.runs import (
    RUN_STATUS_CLAIMED,
    RUN_STATUS_PENDING,
    RUN_STATUS_RUNNING,
    RUN_STATUS_TERMINAL_FAILED,
)
from tests.factories import build_user, build_workspace

pytestmark = pytest.mark.asyncio


async def _schedule_context(
    db: AsyncSession,
    *,
    default_prompt: str | None = "Run the scheduled task",
    execution_params: dict[str, Any] | None = None,
    status: str = RUN_STATUS_CLAIMED,
):
    now = datetime.now(UTC)
    user = build_user(email=f"prepare-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"prepare-{uuid4().hex[:8]}")
    db.add_all([user, workspace])
    await db.flush()

    agent = Agent(
        name="Prepare Agent",
        slug=f"prepare-agent-{uuid4().hex[:8]}",
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
        default_prompt=default_prompt,
        execution_params=execution_params,
    )
    db.add(schedule)
    await db.flush()

    schedule_run = AgentScheduleRun(
        schedule_id=schedule.id,
        workspace_id=workspace.id,
        user_id=user.id,
        agent_id=agent.id,
        scheduled_for=schedule.next_run_at,
        status=status,
        attempt_count=1,
    )
    db.add(schedule_run)
    await db.flush()
    return user, workspace, agent, schedule, schedule_run


async def test_prepare_claimed_run_creates_conversation_and_agent_run(
    db_session: AsyncSession,
) -> None:
    _user, _workspace, agent, schedule, schedule_run = await _schedule_context(db_session)

    prepared = await prepare_schedule_run_execution(
        db_session,
        schedule_run_id=schedule_run.id,
    )

    assert prepared.should_execute is True
    assert prepared.schedule_id == schedule.id
    assert prepared.schedule_run_id == schedule_run.id
    assert prepared.user_prompt == "Run the scheduled task"
    assert schedule_run.status == RUN_STATUS_RUNNING
    assert schedule_run.claim_expires_at is None

    conversation = await db_session.get(Conversation, prepared.conversation_id)
    assert conversation is not None
    assert conversation.source == "scheduled"
    assert conversation.schedule_id == schedule.id
    assert conversation.schedule_run_id == schedule_run.id
    assert conversation.active_agent_id == agent.id
    assert conversation.agent_slug == agent.slug

    run = await db_session.get(AgentRun, prepared.agent_run_id)
    assert run is not None
    assert run.trigger == RUN_TRIGGER_SCHEDULED
    assert run.metadata_json["envelope"] == {"side_effect_policy": "require_approval"}
    assert schedule_run.agent_run_id == run.id


async def test_prepare_claimed_run_stamps_explicit_side_effect_grant(
    db_session: AsyncSession,
) -> None:
    _user, _workspace, _agent, _schedule, schedule_run = await _schedule_context(
        db_session,
        execution_params={"envelope": {"side_effect_policy": "allow"}},
    )

    prepared = await prepare_schedule_run_execution(
        db_session,
        schedule_run_id=schedule_run.id,
    )

    run = await db_session.get(AgentRun, prepared.agent_run_id)
    assert run is not None
    assert run.metadata_json["envelope"] == {"side_effect_policy": "allow"}


@pytest.mark.parametrize("policy", ["allow", "deny"])
async def test_prepare_claimed_run_uses_scheduled_policy_setting(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    policy: str,
) -> None:
    monkeypatch.setattr(settings, "AGENT_SCHEDULED_SIDE_EFFECT_POLICY", policy)
    _user, _workspace, _agent, _schedule, schedule_run = await _schedule_context(db_session)

    prepared = await prepare_schedule_run_execution(
        db_session,
        schedule_run_id=schedule_run.id,
    )

    run = await db_session.get(AgentRun, prepared.agent_run_id)
    assert run is not None
    assert run.metadata_json["envelope"] == {"side_effect_policy": policy}


async def test_prepare_reuses_existing_conversation(db_session: AsyncSession) -> None:
    user, workspace, agent, schedule, schedule_run = await _schedule_context(db_session)
    conversation = Conversation(
        user_id=user.id,
        workspace_id=workspace.id,
        created_by=user.id,
        source="scheduled",
        schedule_id=schedule.id,
        schedule_run_id=schedule_run.id,
        active_agent_id=agent.id,
    )
    db_session.add(conversation)
    await db_session.flush()
    schedule_run.conversation_id = conversation.id

    prepared = await prepare_schedule_run_execution(
        db_session,
        schedule_run_id=schedule_run.id,
    )

    assert prepared.conversation_id == conversation.id
    assert schedule_run.conversation_id == conversation.id


async def test_prepare_missing_default_prompt_terminally_fails_schedule(
    db_session: AsyncSession,
) -> None:
    _user, _workspace, _agent, schedule, schedule_run = await _schedule_context(
        db_session,
        default_prompt="   ",
    )

    prepared = await prepare_schedule_run_execution(
        db_session,
        schedule_run_id=schedule_run.id,
    )

    assert prepared.should_execute is False
    assert schedule_run.status == RUN_STATUS_TERMINAL_FAILED
    assert schedule_run.last_error_code == "missing_default_prompt"
    assert schedule_run.last_error_message == "Schedule has no default prompt to execute."
    assert schedule.is_active is False
    assert schedule.next_run_at is None

    audit_event = await db_session.scalar(
        select(AuditEvent).where(AuditEvent.resource_id == str(schedule.id))
    )
    assert audit_event is not None


async def test_prepare_rejects_non_claimed_schedule_run(db_session: AsyncSession) -> None:
    _user, _workspace, _agent, _schedule, schedule_run = await _schedule_context(
        db_session,
        status=RUN_STATUS_PENDING,
    )

    with pytest.raises(ConflictError):
        await prepare_schedule_run_execution(db_session, schedule_run_id=schedule_run.id)
