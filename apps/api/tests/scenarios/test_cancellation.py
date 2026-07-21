# apps/api/tests/scenarios/test_cancellation.py

"""User-requested cancellation at a live tool boundary."""

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.agent_run import AgentRun
from services.agents.runtime.cancellation import request_agent_run_task_cancel
from services.agents.runtime.sinks import CollectingSink
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)


async def test_mid_tool_cancel_persists_cancelled_without_failed_status(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(
        committed_db_session_factory, tool_names=["scenario_cancel_tool"]
    )
    sink = CollectingSink(run_id=context.run_id, conversation_id=context.conversation_id)
    task = asyncio.create_task(
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
    )
    await _wait_for_run_status(committed_db_session_factory, context.run_id, "running")
    request_agent_run_task_cancel(task, run_id=context.run_id)

    with pytest.raises(asyncio.CancelledError):
        await task

    async with committed_db_session_factory() as db:
        run = await db.get(AgentRun, context.run_id)
        assert run is not None
        assert run.status == "cancelled"
        assert run.error_code is None
    assert [(event.event, event.data["status"]) for event in sink.events[-2:]] == [
        ("run.status", "cancelled"),
        ("done", "cancelled"),
    ]
    assert all(event.event != "error" for event in sink.events)


async def _wait_for_run_status(session_factory, run_id, expected: str) -> None:
    for _ in range(100):
        async with session_factory() as db:
            run = await db.get(AgentRun, run_id)
            if run is not None and run.status == expected:
                return
        await asyncio.sleep(0.01)
    raise AssertionError(f"Run did not reach {expected}")
