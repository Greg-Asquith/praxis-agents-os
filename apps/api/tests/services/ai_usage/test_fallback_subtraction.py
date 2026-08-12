"""Recursive agent-run fallback subtraction tests."""

from datetime import UTC, datetime, timedelta

from pydantic_ai.usage import RunUsage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.agent_run import AgentRun
from models.ai_usage_event import AIUsageEvent
from models.user import User
from models.workspace import Workspace
from services.agent_runs import create_agent_run
from services.ai_usage.agent_run_accounting import AgentRunMeteringContext
from services.ai_usage.record_agent_run_fallback import record_agent_run_fallback
from services.ai_usage.utils import usage_values
from tests.factories import build_conversation
from tests.support.scenario import build_scenario_agent


async def test_recursive_subtraction_uses_time_boundary_and_agent_run_purpose_only(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(db_session_factory)
    started = datetime.now(UTC)
    async with db_session_factory() as db:
        parent = await db.get(AgentRun, context.run_id)
        assert parent is not None
        user = await db.get(User, parent.user_id)
        workspace = await db.get(Workspace, parent.workspace_id)
        assert user is not None and workspace is not None
        child_conversation = build_conversation(
            user=user,
            workspace=workspace,
            active_agent_id=parent.agent_id,
            source="delegated",
        )
        grandchild_conversation = build_conversation(
            user=user,
            workspace=workspace,
            active_agent_id=parent.agent_id,
            source="delegated",
        )
        db.add_all([child_conversation, grandchild_conversation])
        await db.flush()
        child = await create_agent_run(
            db,
            conversation_id=child_conversation.id,
            agent_id=parent.agent_id,
            workspace_id=parent.workspace_id,
            user_id=parent.user_id,
            trigger="delegated",
            parent_run_id=parent.id,
            delegation_depth=1,
        )
        grandchild = await create_agent_run(
            db,
            conversation_id=grandchild_conversation.id,
            agent_id=parent.agent_id,
            workspace_id=parent.workspace_id,
            user_id=parent.user_id,
            trigger="delegated",
            parent_run_id=child.id,
            delegation_depth=2,
        )
        db.add_all(
            [
                _usage_event(child, occurred_at=started - timedelta(microseconds=1), amount=100),
                _usage_event(child, occurred_at=started, amount=10),
                _usage_event(grandchild, occurred_at=started + timedelta(microseconds=1), amount=5),
                _usage_event(
                    grandchild,
                    occurred_at=started,
                    amount=100,
                    purpose="web_search",
                ),
            ]
        )
        await db.flush()

        baseline_usage = RunUsage(
            requests=1,
            input_tokens=5,
            cache_read_tokens=1,
            cache_write_tokens=1,
            output_tokens=2,
        )
        cumulative_usage = RunUsage(
            requests=7,
            input_tokens=35,
            cache_read_tokens=11,
            cache_write_tokens=8,
            output_tokens=17,
        )
        recorded = await record_agent_run_fallback(
            db,
            run=parent,
            metering=AgentRunMeteringContext(
                invocation_started_at=started,
                baseline=usage_values(baseline_usage),
                usage=cumulative_usage,
                provider="openai",
                model="gpt-5.6-luna",
            ),
        )
        assert recorded
        event = await db.scalar(select(AIUsageEvent).where(AIUsageEvent.run_id == parent.id))
        assert event is not None
        assert (
            event.input_tokens,
            event.cache_read_tokens,
            event.cache_write_tokens,
            event.output_tokens,
            event.requests,
        ) == (15, 7, 4, 8, 4)


def _usage_event(
    run: AgentRun,
    *,
    occurred_at: datetime,
    amount: int,
    purpose: str = "agent_run",
) -> AIUsageEvent:
    return AIUsageEvent(
        workspace_id=run.workspace_id,
        provider="openai",
        model="gpt-5.6-luna",
        purpose=purpose,
        run_id=run.id,
        occurred_at=occurred_at,
        input_tokens=amount,
        cache_read_tokens=2 if amount == 10 else 1 if amount == 5 else amount,
        cache_write_tokens=1 if amount == 10 else 2 if amount == 5 else amount,
        output_tokens=4 if amount == 10 else 3 if amount == 5 else amount,
        requests=1,
    )
