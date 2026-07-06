# apps/api/tests/services/agent_runs/test_agent_run_lifecycle.py

"""Behavioural tests for the generic agent_runs lifecycle service.

Covers run creation, valid/invalid status transitions, usage recording, and linkage
from a scheduler claim row to its generic run. Database-backed: skips cleanly without
TEST_DATABASE_URL via the shared db_session fixture chain.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError, CustomValueError
from models.agent import Agent, AgentSchedule, AgentScheduleRun
from models.agent_run import AgentRun
from models.conversation import Conversation
from services.agent_runs import (
    cancel_agent_run,
    complete_agent_run,
    create_agent_run,
    fail_agent_run,
    link_schedule_run,
    mark_run_awaiting_approval,
    record_run_usage,
    start_agent_run,
    start_agent_run_with_lease,
)
from services.agent_runs.domain import (
    RUN_STATUS_AWAITING_APPROVAL,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_PENDING,
    RUN_STATUS_RUNNING,
    RUN_TRIGGER_DELEGATED,
    RunUsageSnapshot,
)
from tests.factories import build_user, build_workspace

pytestmark = pytest.mark.asyncio


@dataclass(frozen=True)
class RunContext:
    """The FK prerequisites a run needs."""

    user_id: UUID
    workspace_id: UUID
    agent_id: UUID
    conversation_id: UUID


@pytest_asyncio.fixture
async def run_context(db_session: AsyncSession) -> RunContext:
    """Persist a user, workspace, agent, and conversation for run tests."""
    user = build_user(email=f"runner-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"ws-{uuid4().hex[:8]}")
    db_session.add_all([user, workspace])
    await db_session.flush()

    agent = Agent(
        name="Runner",
        slug=f"runner-{uuid4().hex[:8]}",
        instructions="do the thing",
        workspace_id=workspace.id,
        created_by=user.id,
    )
    db_session.add(agent)
    await db_session.flush()

    conversation = Conversation(
        user_id=user.id,
        workspace_id=workspace.id,
        created_by=user.id,
    )
    db_session.add(conversation)
    await db_session.flush()

    return RunContext(
        user_id=user.id,
        workspace_id=workspace.id,
        agent_id=agent.id,
        conversation_id=conversation.id,
    )


async def _create(db: AsyncSession, ctx: RunContext, *, trigger: str = "interactive") -> AgentRun:
    return await create_agent_run(
        db,
        conversation_id=ctx.conversation_id,
        agent_id=ctx.agent_id,
        workspace_id=ctx.workspace_id,
        user_id=ctx.user_id,
        trigger=trigger,
        model_name="anthropic:claude-opus-4-8",
    )


async def test_create_agent_run_starts_pending(
    db_session: AsyncSession, run_context: RunContext
) -> None:
    run = await _create(db_session, run_context)
    assert run.id is not None
    assert run.status == RUN_STATUS_PENDING
    assert run.trigger == "interactive"
    assert run.model_name == "anthropic:claude-opus-4-8"
    assert run.started_at is None


async def test_create_rejects_unknown_trigger(
    db_session: AsyncSession, run_context: RunContext
) -> None:
    with pytest.raises(CustomValueError):
        await _create(db_session, run_context, trigger="telepathy")


async def test_create_delegated_run_records_parent_and_depth(
    db_session: AsyncSession, run_context: RunContext
) -> None:
    parent_run = await _create(db_session, run_context)

    child_run = await create_agent_run(
        db_session,
        conversation_id=run_context.conversation_id,
        agent_id=run_context.agent_id,
        workspace_id=run_context.workspace_id,
        user_id=run_context.user_id,
        trigger=RUN_TRIGGER_DELEGATED,
        parent_run_id=parent_run.id,
        delegation_depth=1,
    )

    assert child_run.trigger == RUN_TRIGGER_DELEGATED
    assert child_run.parent_run_id == parent_run.id
    assert child_run.delegation_depth == 1


async def test_create_rejects_negative_delegation_depth(
    db_session: AsyncSession, run_context: RunContext
) -> None:
    with pytest.raises(CustomValueError, match="delegation_depth"):
        await create_agent_run(
            db_session,
            conversation_id=run_context.conversation_id,
            agent_id=run_context.agent_id,
            workspace_id=run_context.workspace_id,
            user_id=run_context.user_id,
            trigger=RUN_TRIGGER_DELEGATED,
            delegation_depth=-1,
        )


async def test_create_rejects_conversation_workspace_mismatch(
    db_session: AsyncSession, run_context: RunContext
) -> None:
    other_workspace = build_workspace(slug=f"ws-{uuid4().hex[:8]}")
    db_session.add(other_workspace)
    await db_session.flush()

    with pytest.raises(ConflictError, match="context is inconsistent"):
        await create_agent_run(
            db_session,
            conversation_id=run_context.conversation_id,
            agent_id=run_context.agent_id,
            workspace_id=other_workspace.id,
            user_id=run_context.user_id,
            trigger="interactive",
        )


async def test_create_rejects_agent_workspace_mismatch(
    db_session: AsyncSession, run_context: RunContext
) -> None:
    other_workspace = build_workspace(slug=f"ws-{uuid4().hex[:8]}")
    db_session.add(other_workspace)
    await db_session.flush()

    other_agent = Agent(
        name="Other Runner",
        slug=f"other-runner-{uuid4().hex[:8]}",
        instructions="do another thing",
        workspace_id=other_workspace.id,
        created_by=run_context.user_id,
    )
    db_session.add(other_agent)
    await db_session.flush()

    with pytest.raises(ConflictError, match="context is inconsistent"):
        await create_agent_run(
            db_session,
            conversation_id=run_context.conversation_id,
            agent_id=other_agent.id,
            workspace_id=run_context.workspace_id,
            user_id=run_context.user_id,
            trigger="interactive",
        )


async def test_create_rejects_conversation_active_agent_mismatch(
    db_session: AsyncSession, run_context: RunContext
) -> None:
    other_agent = Agent(
        name="Other Runner",
        slug=f"other-runner-{uuid4().hex[:8]}",
        instructions="do another thing",
        workspace_id=run_context.workspace_id,
        created_by=run_context.user_id,
    )
    conversation = await db_session.get(Conversation, run_context.conversation_id)
    assert conversation is not None
    conversation.active_agent_id = run_context.agent_id
    db_session.add(other_agent)
    await db_session.flush()

    with pytest.raises(ConflictError, match="context is inconsistent"):
        await create_agent_run(
            db_session,
            conversation_id=run_context.conversation_id,
            agent_id=other_agent.id,
            workspace_id=run_context.workspace_id,
            user_id=run_context.user_id,
            trigger="interactive",
        )


async def test_running_to_completed_stamps_timestamps(
    db_session: AsyncSession, run_context: RunContext
) -> None:
    run = await _create(db_session, run_context)

    await start_agent_run(db_session, run)
    assert run.status == RUN_STATUS_RUNNING
    assert run.started_at is not None

    await complete_agent_run(db_session, run)
    assert run.status == RUN_STATUS_COMPLETED
    assert run.completed_at is not None


async def test_start_with_lease_sets_owner_and_expiry(
    db_session: AsyncSession, run_context: RunContext
) -> None:
    now = datetime.now(UTC)
    run = await _create(db_session, run_context)

    await start_agent_run_with_lease(
        db_session,
        run,
        owner_instance_id="api-1",
        now=now,
        ttl_seconds=30,
    )

    assert run.status == RUN_STATUS_RUNNING
    assert run.started_at is not None
    assert run.owner_instance_id == "api-1"
    assert run.lease_expires_at == now + timedelta(seconds=30)


async def test_awaiting_approval_then_resume(
    db_session: AsyncSession, run_context: RunContext
) -> None:
    run = await _create(db_session, run_context)
    await start_agent_run(db_session, run)

    await mark_run_awaiting_approval(db_session, run)
    assert run.status == RUN_STATUS_AWAITING_APPROVAL

    # resume re-enters running
    await start_agent_run(db_session, run)
    assert run.status == RUN_STATUS_RUNNING


async def test_invalid_transition_from_pending_raises(
    db_session: AsyncSession, run_context: RunContext
) -> None:
    run = await _create(db_session, run_context)
    # pending -> completed is not a permitted edge
    with pytest.raises(ConflictError):
        await complete_agent_run(db_session, run)


async def test_terminal_status_is_final(db_session: AsyncSession, run_context: RunContext) -> None:
    run = await _create(db_session, run_context)
    await start_agent_run(db_session, run)
    await complete_agent_run(db_session, run)

    with pytest.raises(ConflictError):
        await start_agent_run(db_session, run)
    with pytest.raises(ConflictError):
        await cancel_agent_run(db_session, run)


async def test_fail_records_sanitized_error(
    db_session: AsyncSession, run_context: RunContext
) -> None:
    run = await _create(db_session, run_context)
    await start_agent_run(db_session, run)

    await fail_agent_run(
        db_session,
        run,
        error_code="provider_error",
        error_message="boom\n\n   with    messy   whitespace",
    )
    assert run.status == RUN_STATUS_FAILED
    assert run.failed_at is not None
    assert run.error_code == "provider_error"
    assert run.error_message == "boom with messy whitespace"


async def test_record_usage_sets_hot_columns_and_json(
    db_session: AsyncSession, run_context: RunContext
) -> None:
    run = await _create(db_session, run_context)
    await start_agent_run(db_session, run)

    snapshot = RunUsageSnapshot(
        input_tokens=103,
        input_tokens_cached=40,
        output_tokens=15,
        requests=2,
        tool_calls=1,
        raw_json={"input_tokens": 103, "output_tokens": 15, "requests": 2, "tool_calls": 1},
    )
    await record_run_usage(db_session, run, snapshot)

    assert run.input_tokens == 103
    assert run.input_tokens_cached == 40
    assert run.output_tokens == 15
    assert run.requests == 2
    assert run.tool_calls == 1
    assert run.usage_json["input_tokens"] == 103


async def test_link_schedule_run_points_at_generic_run(
    db_session: AsyncSession, run_context: RunContext
) -> None:
    schedule = AgentSchedule(
        agent_id=run_context.agent_id,
        user_id=run_context.user_id,
        workspace_id=run_context.workspace_id,
        schedule_type="once",
        run_once_at=datetime.now(UTC),
    )
    db_session.add(schedule)
    await db_session.flush()

    schedule_run = AgentScheduleRun(
        schedule_id=schedule.id,
        workspace_id=run_context.workspace_id,
        user_id=run_context.user_id,
        agent_id=run_context.agent_id,
        scheduled_for=datetime.now(UTC),
    )
    db_session.add(schedule_run)
    await db_session.flush()

    run = await _create(db_session, run_context, trigger="scheduled")
    await link_schedule_run(db_session, schedule_run, run)

    assert schedule_run.agent_run_id == run.id
    assert run.trigger == "scheduled"


async def test_link_schedule_run_rejects_interactive_run(
    db_session: AsyncSession, run_context: RunContext
) -> None:
    schedule_run = AgentScheduleRun(
        schedule_id=uuid4(),
        workspace_id=run_context.workspace_id,
        user_id=run_context.user_id,
        agent_id=run_context.agent_id,
        scheduled_for=datetime.now(UTC),
    )
    run = await _create(db_session, run_context, trigger="interactive")

    with pytest.raises(ConflictError, match="cannot be linked"):
        await link_schedule_run(db_session, schedule_run, run)


async def test_link_schedule_run_rejects_context_mismatch(
    db_session: AsyncSession, run_context: RunContext
) -> None:
    other_user = build_user(email=f"other-runner-{uuid4().hex}@example.com")
    db_session.add(other_user)
    await db_session.flush()

    schedule_run = AgentScheduleRun(
        schedule_id=uuid4(),
        workspace_id=run_context.workspace_id,
        user_id=other_user.id,
        agent_id=run_context.agent_id,
        scheduled_for=datetime.now(UTC),
    )
    run = await _create(db_session, run_context, trigger="scheduled")

    with pytest.raises(ConflictError, match="cannot be linked"):
        await link_schedule_run(db_session, schedule_run, run)
