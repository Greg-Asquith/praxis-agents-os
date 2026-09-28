# apps/api/tests/services/agent_runs/test_agent_run_lifecycle.py

"""Behavioural tests for the generic agent_runs lifecycle service.

Covers run creation, valid/invalid status transitions, usage recording, and linkage
from a scheduler claim row to its generic run. Database-backed: skips cleanly without
TEST_DATABASE_URL via the shared db_session fixture chain.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.database import set_session_tenant_context
from core.exceptions.general import ConflictError, CustomValueError, NotFoundError
from models.agent import Agent, AgentScheduleRun
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
    renew_agent_run_lease,
    start_agent_run,
    start_agent_run_with_lease,
)
from services.agent_runs.domain import (
    RUN_OUTCOME_BLOCKED,
    RUN_OUTCOME_CANCELLED,
    RUN_OUTCOME_ERROR,
    RUN_OUTCOME_SUCCESS,
    RUN_STATUS_CANCELLED,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
)
from tests.factories import build_user, build_workspace, build_workspace_membership

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


@pytest.mark.parametrize(
    "owner,elapsed,expected", [("old", 1, False), ("current", 30, False), ("current", 1, True)]
)
async def test_renewal_cannot_steal_or_revive_lease(
    db_session: AsyncSession, run_context: RunContext, owner: str, elapsed: int, expected: bool
) -> None:
    now = datetime.now(UTC)
    run = await _create(db_session, run_context)
    await start_agent_run_with_lease(
        db_session, run, owner_instance_id="current", now=now, ttl_seconds=30
    )
    renewed = await renew_agent_run_lease(
        db_session,
        run_id=run.id,
        owner_instance_id=owner,
        workspace_id=run_context.workspace_id,
        user_id=run_context.user_id,
        now=now + timedelta(seconds=elapsed),
        ttl_seconds=30,
    )
    assert renewed is expected
    await db_session.refresh(run)
    assert run.owner_instance_id == "current"
    assert run.lease_expires_at == now + timedelta(seconds=31 if expected else 30)


async def test_start_cannot_replace_live_owner(
    db_session: AsyncSession, run_context: RunContext
) -> None:
    run = await _create(db_session, run_context)
    await start_agent_run_with_lease(db_session, run, owner_instance_id="current")
    with pytest.raises(ConflictError):
        await start_agent_run_with_lease(db_session, run, owner_instance_id="old")
    await db_session.refresh(run)
    assert run.owner_instance_id == "current"


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


@pytest.mark.parametrize("snapshot", [None, {}, {"version": 1, "limits": {"request_limit": 999}}])
async def test_create_rejects_caller_supplied_effective_budget(db_session, run_context, snapshot):
    with pytest.raises(CustomValueError, match="owned by run execution"):
        await create_agent_run(
            db_session,
            conversation_id=run_context.conversation_id,
            agent_id=run_context.agent_id,
            workspace_id=run_context.workspace_id,
            user_id=run_context.user_id,
            trigger="interactive",
            metadata={"effective_usage_limits": snapshot},
        )
