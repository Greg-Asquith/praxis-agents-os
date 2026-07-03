# apps/api/tests/services/agent_schedules/test_claim_runs.py

"""Tests for claiming due schedule run attempts."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent, AgentSchedule, AgentScheduleRun
from services.agent_schedules.runs import (
    RUN_STATUS_AWAITING_APPROVAL,
    RUN_STATUS_CLAIMED,
    claim_due_schedule_runs,
)
from tests.factories import build_user, build_workspace

pytestmark = pytest.mark.asyncio


async def test_claim_due_schedule_runs_skips_blocked_current_fire_time(
    db_session: AsyncSession,
) -> None:
    now = datetime(2000, 1, 1, 0, 3, tzinfo=UTC)
    user = build_user(email=f"claim-schedule-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"claim-schedule-{uuid4().hex[:8]}")
    db_session.add_all([user, workspace])
    await db_session.flush()

    agent = Agent(
        name="Claim Schedule Agent",
        slug=f"claim-schedule-agent-{uuid4().hex[:8]}",
        instructions="Reply plainly.",
        workspace_id=workspace.id,
        created_by=user.id,
    )
    db_session.add(agent)
    await db_session.flush()

    blocked = AgentSchedule(
        agent_id=agent.id,
        user_id=user.id,
        workspace_id=workspace.id,
        schedule_type="once",
        run_once_at=now - timedelta(minutes=2),
        next_run_at=now - timedelta(minutes=2),
        default_prompt="Already waiting for approval",
    )
    claimable = AgentSchedule(
        agent_id=agent.id,
        user_id=user.id,
        workspace_id=workspace.id,
        schedule_type="once",
        run_once_at=now - timedelta(minutes=1),
        next_run_at=now - timedelta(minutes=1),
        default_prompt="Run this schedule",
    )
    db_session.add_all([blocked, claimable])
    await db_session.flush()

    blocked_run = AgentScheduleRun(
        schedule_id=blocked.id,
        workspace_id=workspace.id,
        user_id=user.id,
        agent_id=agent.id,
        scheduled_for=blocked.next_run_at,
        status=RUN_STATUS_AWAITING_APPROVAL,
        attempt_count=1,
    )
    db_session.add(blocked_run)
    await db_session.flush()

    claimed = await claim_due_schedule_runs(db_session, now=now, batch_size=1)

    assert [claimed_run.schedule.id for claimed_run in claimed] == [claimable.id]
    assert claimed[0].run.schedule_id == claimable.id
    assert claimed[0].run.status == RUN_STATUS_CLAIMED
    assert blocked_run.status == RUN_STATUS_AWAITING_APPROVAL
