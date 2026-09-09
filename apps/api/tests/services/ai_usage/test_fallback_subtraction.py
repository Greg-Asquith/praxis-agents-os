"""Invocation attribution remains independent of child commit timing."""

from pydantic_ai.usage import RunUsage
from sqlalchemy import select

from models.agent_run import AgentRun
from models.ai_usage_event import AIUsageEvent
from services.ai_usage.agent_run_accounting import AgentRunMeteringContext
from services.ai_usage.record_agent_run_fallback import record_agent_run_fallback
from services.ai_usage.utils import usage_values
from tests.support.scenario import build_scenario_agent


async def test_child_usage_is_subtracted_before_any_child_ledger_commit(db_session_factory):
    context = await build_scenario_agent(db_session_factory)
    shared = RunUsage(
        input_tokens=100, cache_read_tokens=10, cache_write_tokens=5, output_tokens=40, requests=2
    )
    parent = AgentRunMeteringContext(
        baseline=usage_values(shared), usage=shared, provider="openai", model="parent"
    )
    shared.input_tokens += 10
    shared.cache_read_tokens += 2
    shared.cache_write_tokens += 1
    shared.output_tokens += 3
    shared.requests += 1
    child = AgentRunMeteringContext(
        baseline=usage_values(shared),
        usage=shared,
        provider="google",
        model="child",
        parent=parent,
    )
    shared.input_tokens += 25
    shared.cache_read_tokens += 4
    shared.cache_write_tokens += 2
    shared.output_tokens += 7
    shared.requests += 2
    assert child.freeze()["input_tokens"] == 25
    shared.input_tokens += 5
    shared.cache_read_tokens += 1
    shared.cache_write_tokens += 1
    shared.output_tokens += 4
    shared.requests += 1
    assert child.freeze()["input_tokens"] == 25
    assert parent.freeze()["input_tokens"] == 15
    shared.input_tokens += 99
    async with db_session_factory() as db:
        run = await db.get(AgentRun, context.run_id)
        assert await record_agent_run_fallback(db, run=run, metering=parent)
        assert await record_agent_run_fallback(db, run=run, metering=parent)
        [event] = (
            await db.scalars(select(AIUsageEvent).where(AIUsageEvent.run_id == run.id))
        ).all()
        assert (
            event.input_tokens,
            event.cache_read_tokens,
            event.cache_write_tokens,
            event.output_tokens,
            event.requests,
            event.model,
        ) == (15, 3, 2, 7, 2, "parent")


def test_child_and_grandchild_freeze_aggregate_each_interval_once():
    shared = RunUsage()
    parent = AgentRunMeteringContext(
        baseline=usage_values(shared), usage=shared, provider="openai", model="parent"
    )
    shared.input_tokens += 3
    child = AgentRunMeteringContext(
        baseline=usage_values(shared), usage=shared, provider="google", model="child", parent=parent
    )
    shared.input_tokens += 7
    grandchild = AgentRunMeteringContext(
        baseline=usage_values(shared),
        usage=shared,
        provider="google",
        model="grandchild",
        parent=child,
    )
    shared.input_tokens += 11
    assert grandchild.freeze()["input_tokens"] == 11
    assert child.freeze()["input_tokens"] == 7
    assert child.freeze()["input_tokens"] == 7
    assert parent.freeze()["input_tokens"] == 3
