# apps/api/tests/services/agent_runs/test_agent_run_lifecycle.py

"""Behavioural tests for the generic agent_runs lifecycle service.

Covers run creation, valid/invalid status transitions, usage recording, and linkage
from a scheduler claim row to its generic run. Database-backed: skips cleanly without
TEST_DATABASE_URL via the shared db_session fixture chain.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from runpy import run_path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.database import set_session_tenant_context
from core.exceptions.general import ConflictError, CustomValueError, NotFoundError
from models.agent import Agent, AgentSchedule, AgentScheduleRun
from models.agent_run import AgentRun
from models.conversation import Conversation
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
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
    RUN_OUTCOME_BLOCKED,
    RUN_OUTCOME_BUDGET_EXHAUSTED,
    RUN_OUTCOME_CANCELLED,
    RUN_OUTCOME_ERROR,
    RUN_OUTCOME_SUCCESS,
    RUN_STATUS_AWAITING_APPROVAL,
    RUN_STATUS_CANCELLED,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_PENDING,
    RUN_STATUS_RUNNING,
    RUN_TRIGGER_DELEGATED,
    RunUsageSnapshot,
)
from services.completion_contract import MAX_COMPLETION_JSON_BYTES
from tests.factories import build_user, build_workspace, build_workspace_membership

pytestmark = pytest.mark.asyncio

CORE_0035_BACKFILL_SQL = run_path(
    str(
        Path(__file__).resolve().parents[3] / "alembic/versions/core/0035_add_agent_run_outcomes.py"
    )
)["AGENT_RUN_OUTCOME_BACKFILL_SQL"]


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
    child_conversation = Conversation(
        user_id=run_context.user_id,
        workspace_id=run_context.workspace_id,
        created_by=run_context.user_id,
        active_agent_id=run_context.agent_id,
        source="delegated",
    )
    db_session.add(child_conversation)
    await db_session.flush()

    child_run = await create_agent_run(
        db_session,
        conversation_id=child_conversation.id,
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

    await set_session_tenant_context(
        db_session,
        workspace_id=run_context.workspace_id,
        user_id=run_context.user_id,
    )
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

    await set_session_tenant_context(
        db_session,
        workspace_id=run_context.workspace_id,
        user_id=run_context.user_id,
    )
    with pytest.raises(NotFoundError, match="Agent not found"):
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
    assert run.outcome == RUN_OUTCOME_SUCCESS
    assert run.completion_json is None


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


async def test_resume_restarts_runtime_clock(
    db_session: AsyncSession, run_context: RunContext
) -> None:
    run = await _create(db_session, run_context)
    await start_agent_run(db_session, run)
    stale_started_at = datetime.now(UTC) - timedelta(hours=1)
    run.started_at = stale_started_at
    await db_session.flush()
    await mark_run_awaiting_approval(db_session, run)

    await start_agent_run(db_session, run)

    assert run.started_at is not None
    assert run.started_at > stale_started_at + timedelta(minutes=30)


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
    assert run.outcome == RUN_OUTCOME_ERROR
    assert run.completion_json == {"error_code": "provider_error"}


async def test_terminal_outcome_is_written_once(
    db_session: AsyncSession, run_context: RunContext
) -> None:
    run = await _create(db_session, run_context)
    await start_agent_run(db_session, run)
    await complete_agent_run(
        db_session,
        run,
        completion_json={"summary": "first terminal evidence"},
    )

    await complete_agent_run(
        db_session,
        run,
        completion_json={"summary": "replacement must not be written"},
    )

    assert run.outcome == RUN_OUTCOME_SUCCESS
    assert run.completion_json == {"summary": "first terminal evidence"}


@pytest.mark.parametrize(
    ("left_target", "right_target"),
    [
        (RUN_STATUS_COMPLETED, RUN_STATUS_CANCELLED),
        ("code_mode_recovery", RUN_STATUS_CANCELLED),
        ("code_mode_recovery", RUN_STATUS_COMPLETED),
    ],
)
async def test_competing_terminal_transitions_preserve_first_outcome(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    left_target: str,
    right_target: str,
) -> None:
    suffix = uuid4().hex
    user = build_user(email=f"terminal-race-{suffix}@example.com")
    workspace = build_workspace(slug=f"terminal-race-{suffix[:8]}")
    membership = build_workspace_membership(workspace_id=workspace.id, user_id=user.id)
    async with committed_db_session_factory() as setup_db:
        setup_db.add_all([user, workspace, membership])
        await setup_db.flush()
        agent = Agent(
            name="Terminal Race Agent",
            slug=f"terminal-race-{suffix[:8]}",
            instructions="Reply plainly.",
            workspace_id=workspace.id,
            created_by=user.id,
        )
        conversation = Conversation(
            user_id=user.id,
            workspace_id=workspace.id,
            created_by=user.id,
        )
        setup_db.add_all([agent, conversation])
        await setup_db.flush()
        run = await create_agent_run(
            setup_db,
            conversation_id=conversation.id,
            agent_id=agent.id,
            workspace_id=workspace.id,
            user_id=user.id,
            trigger="interactive",
        )
        await start_agent_run(setup_db, run)
        await setup_db.commit()

    barrier = asyncio.Barrier(2)

    async def finish(target: str) -> str:
        async with committed_db_session_factory() as db:
            await set_session_tenant_context(
                db,
                workspace_id=workspace.id,
                user_id=user.id,
            )
            stale_run = await db.get(AgentRun, run.id)
            assert stale_run is not None
            await asyncio.wait_for(barrier.wait(), timeout=5)
            try:
                if target == "code_mode_recovery":
                    await fail_agent_run(
                        db,
                        stale_run,
                        error_code="code_mode_resume_requires_recovery",
                        completion_json={
                            "error_code": "code_mode_resume_requires_recovery",
                            "degradation_reason": "resume_crash",
                            "executed_effects": [],
                        },
                    )
                elif target == RUN_STATUS_COMPLETED:
                    await complete_agent_run(db, stale_run)
                else:
                    await cancel_agent_run(db, stale_run)
                await db.commit()
                return target
            except ConflictError:
                await db.rollback()
                return "conflict"

    try:
        results = await asyncio.wait_for(
            asyncio.gather(
                finish(left_target),
                finish(right_target),
                return_exceptions=True,
            ),
            timeout=10,
        )
        assert not [result for result in results if isinstance(result, BaseException)]
        assert results.count("conflict") == 1
        winning_status = next(result for result in results if result != "conflict")

        async with committed_db_session_factory() as verify_db:
            await set_session_tenant_context(
                verify_db,
                workspace_id=workspace.id,
                user_id=user.id,
            )
            stored = await verify_db.get(AgentRun, run.id)
            assert stored is not None
            expected_status = (
                RUN_STATUS_FAILED if winning_status == "code_mode_recovery" else winning_status
            )
            assert stored.status == expected_status
            expected_outcomes = {
                "code_mode_recovery": RUN_OUTCOME_BLOCKED,
                RUN_STATUS_COMPLETED: RUN_OUTCOME_SUCCESS,
                RUN_STATUS_CANCELLED: RUN_OUTCOME_CANCELLED,
            }
            assert stored.outcome == expected_outcomes[winning_status]
            if winning_status == "code_mode_recovery":
                assert stored.error_code == "code_mode_resume_requires_recovery"
                assert stored.completion_json == {
                    "error_code": "code_mode_resume_requires_recovery",
                    "degradation_reason": "resume_crash",
                    "executed_effects": [],
                }
    finally:
        async with committed_db_session_factory() as cleanup_db:
            await set_session_tenant_context(
                cleanup_db,
                workspace_id=workspace.id,
                user_id=user.id,
            )
            await cleanup_db.execute(delete(AgentRun).where(AgentRun.id == run.id))
            await cleanup_db.execute(delete(Conversation).where(Conversation.id == conversation.id))
            await cleanup_db.execute(delete(Agent).where(Agent.id == agent.id))
            await cleanup_db.execute(
                delete(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace.id)
            )
            await cleanup_db.execute(delete(Workspace).where(Workspace.id == workspace.id))
            await cleanup_db.execute(delete(User).where(User.id == user.id))
            await cleanup_db.commit()


async def test_core_0035_backfills_legacy_terminal_outcomes(
    db_session: AsyncSession,
    run_context: RunContext,
) -> None:
    cases = [
        ("completed", None, "success", None),
        ("cancelled", None, "cancelled", None),
        ("failed", "approval_expired", "blocked", {"error_code": "approval_expired"}),
        (
            "failed",
            "usage_limit_exceeded",
            "budget_exhausted",
            {"error_code": "usage_limit_exceeded"},
        ),
        ("failed", "run_abandoned", "error", {"error_code": "run_abandoned"}),
        ("failed", "provider_error", "error", {"error_code": "provider_error"}),
        ("failed", None, "error", {"error_code": "agent_run_failed"}),
    ]
    runs = [
        AgentRun(
            conversation_id=run_context.conversation_id,
            agent_id=run_context.agent_id,
            workspace_id=run_context.workspace_id,
            user_id=run_context.user_id,
            trigger="interactive",
            status=status,
            error_code=error_code,
        )
        for status, error_code, _outcome, _completion_json in cases
    ]
    pending = AgentRun(
        conversation_id=run_context.conversation_id,
        agent_id=run_context.agent_id,
        workspace_id=run_context.workspace_id,
        user_id=run_context.user_id,
        trigger="interactive",
        status=RUN_STATUS_PENDING,
    )
    db_session.add_all([*runs, pending])
    await db_session.flush()

    await db_session.execute(text(str(CORE_0035_BACKFILL_SQL)))
    refreshed = list(
        (
            await db_session.scalars(
                select(AgentRun)
                .where(AgentRun.id.in_([run.id for run in runs]))
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    by_id = {run.id: run for run in refreshed}

    for run, (_status, _error_code, expected_outcome, expected_completion) in zip(
        runs, cases, strict=True
    ):
        assert by_id[run.id].outcome == expected_outcome
        assert by_id[run.id].completion_json == expected_completion

    await db_session.refresh(pending)
    assert pending.outcome is None
    assert pending.completion_json is None


async def test_completion_json_rejects_oversized_evidence_before_transition(
    db_session: AsyncSession, run_context: RunContext
) -> None:
    run = await _create(db_session, run_context)
    await start_agent_run(db_session, run)

    with pytest.raises(ValueError, match="must not exceed"):
        await complete_agent_run(
            db_session,
            run,
            completion_json={"summary": "x" * MAX_COMPLETION_JSON_BYTES},
        )

    assert run.status == RUN_STATUS_RUNNING
    assert run.outcome is None


@pytest.mark.parametrize(
    ("error_code", "expected_outcome"),
    [
        ("usage_limit_exceeded", RUN_OUTCOME_BUDGET_EXHAUSTED),
        ("provider_error", RUN_OUTCOME_ERROR),
    ],
)
async def test_failure_outcome_taxonomy(
    db_session: AsyncSession,
    run_context: RunContext,
    error_code: str,
    expected_outcome: str,
) -> None:
    run = await _create(db_session, run_context)
    await start_agent_run(db_session, run)

    await fail_agent_run(db_session, run, error_code=error_code, error_message="stopped")

    assert run.outcome == expected_outcome
    assert run.completion_json == {"error_code": error_code}


async def test_cancelled_run_stamps_cancelled_outcome(
    db_session: AsyncSession, run_context: RunContext
) -> None:
    run = await _create(db_session, run_context)
    await start_agent_run(db_session, run)
    run.metadata_json = {
        "approval_state": {"version": 1},
        "code_mode_state": {"snapshot_b64": "opaque"},
        "retained": True,
    }

    await cancel_agent_run(db_session, run)

    assert run.status == RUN_STATUS_CANCELLED
    assert run.outcome == RUN_OUTCOME_CANCELLED
    assert run.completion_json is None
    assert run.metadata_json == {"retained": True}


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
