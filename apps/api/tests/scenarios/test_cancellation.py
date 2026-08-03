# apps/api/tests/scenarios/test_cancellation.py

"""User-requested cancellation at a live tool boundary."""

import asyncio
import importlib
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.agent_run import AgentRun
from services.agent_runs import cancel_agent_run
from services.agents.runtime.cancellation import request_agent_run_task_cancel
from services.agents.runtime.sinks import CollectingSink
from services.agents.runtime.tools.contract import TOOL_EFFECT_WRITE
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG, runtime_tool
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)

dispatch_module = importlib.import_module("services.agents.runtime.dispatch")


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


async def test_remote_cancellation_prevents_pending_tool_side_effect(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_name = f"scenario_remote_cancel_{uuid4().hex}"
    side_effect_started = False

    @runtime_tool(
        name=tool_name,
        provider="test",
        description="Record whether a cancelled tool handler started.",
        effect=TOOL_EFFECT_WRITE,
        configurable=False,
    )
    async def remote_cancel_tool() -> str:
        nonlocal side_effect_started
        side_effect_started = True
        return "started"

    context = await build_scenario_agent(
        committed_db_session_factory,
        tool_names=[tool_name],
    )
    gate_reached = asyncio.Event()
    release_gate = asyncio.Event()
    durable_cancel_check = dispatch_module.raise_if_agent_run_cancelled

    async def paused_cancel_check(*, run_id, workspace_id, user_id):
        gate_reached.set()
        await release_gate.wait()
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

    task = asyncio.create_task(
        run_scenario(
            committed_db_session_factory,
            context,
            model=scripted_model(
                turns=[
                    ToolTurn((ToolCall(tool_name, {}, "remote-cancel-call"),)),
                ]
            ),
        )
    )
    try:
        await asyncio.wait_for(gate_reached.wait(), timeout=2)
        async with committed_db_session_factory() as remote_db:
            run = await remote_db.get(AgentRun, context.run_id)
            assert run is not None
            await cancel_agent_run(remote_db, run)
            await remote_db.commit()

        release_gate.set()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert side_effect_started is False
        async with committed_db_session_factory() as db:
            run = await db.get(AgentRun, context.run_id)
            assert run is not None
            assert run.status == "cancelled"
    finally:
        release_gate.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        RUNTIME_TOOL_CATALOG.pop(tool_name, None)


async def _wait_for_run_status(session_factory, run_id, expected: str) -> None:
    for _ in range(100):
        async with session_factory() as db:
            run = await db.get(AgentRun, run_id)
            if run is not None and run.status == expected:
                return
        await asyncio.sleep(0.01)
    raise AssertionError(f"Run did not reach {expected}")
