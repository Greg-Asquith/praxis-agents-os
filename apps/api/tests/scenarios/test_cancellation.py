# apps/api/tests/scenarios/test_cancellation.py

"""User-requested cancellation at a live tool boundary."""

import asyncio
import importlib
from dataclasses import replace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.database import set_session_tenant_context
from models.agent_run import AgentRun
from models.ai_usage_event import AIUsageEvent
from services.agent_runs import cancel_agent_run
from services.agents.runtime.cancellation import request_agent_run_task_cancel
from services.agents.runtime.sinks import CollectingSink
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from tests.support.delegation import scenario_effects
from tests.support.scenario import (
    ScenarioBarrier,
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)

dispatch_module = importlib.import_module("services.agents.runtime.dispatch")


async def test_mid_tool_cancel_persists_cancelled_without_failed_status(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = await build_scenario_agent(
        committed_db_session_factory, tool_names=["scenario_cancel_tool"]
    )
    sink = CollectingSink(run_id=context.run_id, conversation_id=context.conversation_id)
    barrier = ScenarioBarrier()
    invocations = 0

    async def waiting_tool(ctx):
        nonlocal invocations
        invocations += 1
        await barrier.pause()
        return "released"

    definition = RUNTIME_TOOL_CATALOG["scenario_cancel_tool"]
    monkeypatch.setitem(
        RUNTIME_TOOL_CATALOG, definition.name, replace(definition, function=waiting_tool)
    )
    async with barrier.running(
        run_scenario(
            committed_db_session_factory,
            context,
            model=scripted_model(
                turns=[
                    ToolTurn((ToolCall("scenario_cancel_tool", {}, "cancel-call"),)),
                ]
            ),
            sink=sink,
        )
    ) as task:
        await asyncio.wait_for(barrier.reached.wait(), timeout=2)
        assert invocations == 1
        request_agent_run_task_cancel(task, run_id=context.run_id)

        with pytest.raises(asyncio.CancelledError):
            await task

    async with committed_db_session_factory() as db:
        await set_session_tenant_context(db, workspace_id=context.workspace_id)
        run = await db.get(AgentRun, context.run_id)
        assert run is not None
        assert run.status == "cancelled"
        assert run.error_code is None
        [usage_event] = (
            await db.scalars(select(AIUsageEvent).where(AIUsageEvent.run_id == context.run_id))
        ).all()
        assert usage_event.requests == 1
        assert usage_event.details == {"usage_source": "accumulator_delta"}
    assert [(event.event, event.data["status"]) for event in sink.events[-2:]] == [
        ("run.status", "cancelled"),
        ("done", "cancelled"),
    ]
    assert all(event.event != "error" for event in sink.events)


async def test_remote_cancellation_prevents_pending_tool_side_effect(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with scenario_effects() as effects:
        context = await build_scenario_agent(
            committed_db_session_factory,
            tool_names=[effects.name],
        )
        barrier = ScenarioBarrier()
        durable_cancel_check = dispatch_module.raise_if_agent_run_cancelled

        async def paused_cancel_check(*, run_id, workspace_id, user_id):
            await barrier.pause()
            await durable_cancel_check(
                run_id=run_id,
                workspace_id=workspace_id,
                user_id=user_id,
            )

        monkeypatch.setattr(
            dispatch_module,
            "raise_if_agent_run_cancelled",
            paused_cancel_check,
        )

        async with barrier.running(
            run_scenario(
                committed_db_session_factory,
                context,
                model=scripted_model(
                    turns=[
                        ToolTurn(
                            (ToolCall(effects.name, {"value": "external"}, "remote-cancel-call"),)
                        ),
                    ]
                ),
            )
        ) as task:
            await asyncio.wait_for(barrier.reached.wait(), timeout=2)
            async with committed_db_session_factory() as remote_db:
                run = await remote_db.get(AgentRun, context.run_id)
                assert run is not None
                await cancel_agent_run(remote_db, run)
                await remote_db.commit()

            barrier.release.set()
            with pytest.raises(asyncio.CancelledError):
                await task

            assert effects.calls == []
            async with committed_db_session_factory() as db:
                run = await db.get(AgentRun, context.run_id)
                assert run is not None
                assert run.status == "cancelled"
