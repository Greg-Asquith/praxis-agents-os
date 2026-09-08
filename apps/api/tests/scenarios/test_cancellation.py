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


@pytest.mark.parametrize("attempt", ["suspension", "success", "failure", "cancellation"])
@pytest.mark.parametrize("winner", ["cancelled", "reaped"])
async def test_terminal_winner_controls_finalisation(
    committed_db_session_factory, monkeypatch, attempt, winner
):
    from datetime import UTC, datetime, timedelta

    from pydantic_ai import DeferredToolRequests

    from services.agent_runs.reap_abandoned import reap_abandoned_runs

    execution = importlib.import_module("services.agents.runtime.execute.execute_run")
    context = await build_scenario_agent(
        committed_db_session_factory,
        tool_names=["scenario_external_write"],
        tool_policies={"scenario_external_write": "approval"},
    )
    sink = CollectingSink(run_id=context.run_id, conversation_id=context.conversation_id)
    barrier = ScenarioBarrier()
    boundary = {
        "failure": "emit_failure_events",
        "cancellation": "finalize_cancelled_run",
    }.get(attempt, "finalize_terminal_run")
    finalisation = execution
    if attempt == "failure":
        finalisation = importlib.import_module("services.agents.runtime.execute.settle_failure")
    elif attempt == "cancellation":
        finalisation = importlib.import_module(
            "services.agents.runtime.execute.settle_interruption"
        )
    original = getattr(finalisation, boundary)

    async def paused_finalisation(db=None, **kwargs):
        if db is not None:
            await db.commit()
        await barrier.pause()
        return await original(db, **kwargs) if db is not None else await original(**kwargs)

    if attempt == "cancellation":
        original_consume = execution.consume_stream

        async def cancelled_stream(*args, **kwargs):
            from services.agents.runtime.cancellation import AGENT_RUN_CANCEL_REQUEST

            await original_consume(*args, **kwargs)
            raise asyncio.CancelledError(AGENT_RUN_CANCEL_REQUEST)

        monkeypatch.setattr(execution, "consume_stream", cancelled_stream)

    monkeypatch.setattr(finalisation, boundary, paused_finalisation)
    turns = {
        "suspension": [ToolTurn((ToolCall("scenario_external_write", {"value": "ok"}, "write"),))],
        "success": ["Done."],
        "failure": [],
        "cancellation": ["Done."],
    }[attempt]
    async with barrier.running(
        run_scenario(
            committed_db_session_factory,
            context,
            model=scripted_model(turns=turns),
            sink=sink,
        )
    ) as task:
        await asyncio.wait_for(barrier.reached.wait(), timeout=3)
        async with committed_db_session_factory() as remote:
            run = await remote.get(AgentRun, context.run_id)
            if winner == "cancelled":
                await cancel_agent_run(remote, run)
            else:
                run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
                await remote.flush()
                await reap_abandoned_runs(remote, run_id=run.id)
            await remote.commit()
            expected = (run.status, run.error_code, run.error_message, run.completion_json)
        barrier.release.set()
        if attempt in {"failure", "cancellation"}:
            with pytest.raises(AssertionError if attempt == "failure" else asyncio.CancelledError):
                await task
        else:
            result = await task
            assert result.run.status == expected[0]
            assert not isinstance(result.output, DeferredToolRequests)
            assert result.output is None
    async with committed_db_session_factory() as verify:
        run = await verify.get(AgentRun, context.run_id)
        assert (run.status, run.error_code, run.error_message, run.completion_json) == expected
    assert not any(event.event == "tool.approval_required" for event in sink.events)
    assert sink.events[-1].data["status"] == expected[0]
    errors = [event for event in sink.events if event.event == "error"]
    assert [(event.data["code"], event.data["message"]) for event in errors] == (
        [(expected[1], expected[2])] if winner == "reaped" else []
    )


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
        assert usage_event.details["usage_source"] == "accumulator_delta"
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


@pytest.mark.parametrize("human_cancel", [False, True])
@pytest.mark.parametrize("rollback_failure", ["blocked", "error"])
async def test_interruption_bounds_owner_rollback_and_preserves_cancellation(
    committed_db_session_factory, monkeypatch, human_cancel, rollback_failure
):
    from services.agents.runtime.cancellation import AGENT_RUN_CANCEL_REQUEST

    execution = importlib.import_module("services.agents.runtime.execute.execute_run")
    context = await build_scenario_agent(committed_db_session_factory)
    original_consume = execution.consume_stream
    rollback_entered = asyncio.Event()
    rollback_exited = asyncio.Event()
    owner_tasks = []

    async def interrupted_stream(*args, **kwargs):
        await original_consume(*args, **kwargs)
        db = kwargs["deps"].db
        await db.commit()
        owner = asyncio.current_task()

        async def broken_rollback():
            owner_tasks.append(asyncio.current_task() is owner)
            rollback_entered.set()
            try:
                if rollback_failure == "error":
                    raise RuntimeError("rollback unavailable")
                await asyncio.Event().wait()
            finally:
                rollback_exited.set()

        monkeypatch.setattr(db, "rollback", broken_rollback)
        db.expire_all()
        raise asyncio.CancelledError(AGENT_RUN_CANCEL_REQUEST if human_cancel else "shutdown")

    monkeypatch.setattr(execution, "consume_stream", interrupted_stream)
    monkeypatch.setattr(execution, "CANCEL_FINALIZE_TIMEOUT", 0.5)
    task = asyncio.create_task(
        run_scenario(committed_db_session_factory, context, model=scripted_model(turns=["Done."]))
    )
    try:
        await asyncio.wait_for(rollback_entered.wait(), timeout=3)
        if rollback_failure == "blocked":
            task.cancel("repeated shutdown")
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)
        assert rollback_exited.is_set()
        assert owner_tasks and all(owner_tasks)
        assert not [
            task for task in asyncio.all_tasks() if task.get_name() == "agent-run-finalisation"
        ]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    async with committed_db_session_factory() as db:
        run = await db.get(AgentRun, context.run_id)
        assert run.status == ("cancelled" if human_cancel else "running")
        [event] = (
            await db.scalars(select(AIUsageEvent).where(AIUsageEvent.run_id == context.run_id))
        ).all()
        assert event.requests == 1


@pytest.mark.parametrize("boundary", ["rollback", "commit"])
@pytest.mark.parametrize("human_cancel", [False, True])
@pytest.mark.parametrize("winner", [None, "reaped", "cancelled"])
@pytest.mark.parametrize("settlement_blocked", [False, True])
async def test_cancellation_during_failure_settlement(
    committed_db_session_factory,
    monkeypatch,
    caplog,
    boundary,
    human_cancel,
    winner,
    settlement_blocked,
):
    from datetime import UTC, datetime, timedelta

    from services.agent_runs.reap_abandoned import reap_abandoned_runs
    from services.agents.runtime.cancellation import AGENT_RUN_CANCEL_REQUEST
    from services.ai_usage.record_in_transaction import record_ai_usage_in_transaction

    execution = importlib.import_module("services.agents.runtime.execute.execute_run")
    context = await build_scenario_agent(committed_db_session_factory)
    original_consume = execution.consume_stream
    failure_module = importlib.import_module("services.agents.runtime.execute.settle_failure")
    interruption = importlib.import_module("services.agents.runtime.execute.settle_interruption")
    original_failure = failure_module.emit_failure_events
    original_cancel = interruption.finalize_cancelled_run
    original_usage = interruption.finalize_interrupted_usage
    failure_barrier = ScenarioBarrier()
    isolated_barrier = ScenarioBarrier()
    captured = []
    rollback_owners = []
    expected = None

    async def failing_stream(*args, **kwargs):
        await original_consume(*args, **kwargs)
        raise RuntimeError("Model failed after accruing usage")

    async def failure(db, **kwargs):
        nonlocal expected
        captured.append(kwargs["metering"].event())
        await db.rollback()
        if winner is not None:
            async with committed_db_session_factory() as remote:
                run = await remote.get(AgentRun, context.run_id)
                if winner == "cancelled":
                    await cancel_agent_run(remote, run)
                else:
                    run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
                    await remote.flush()
                    await reap_abandoned_runs(remote, run_id=run.id)
                await remote.commit()
                expected = (run.status, run.error_code, run.error_message, run.completion_json)
        owner = asyncio.current_task()
        rollback = db.rollback
        commit = db.commit
        first_rollback = True

        async def paused_rollback():
            nonlocal first_rollback
            rollback_owners.append(asyncio.current_task() is owner)
            if boundary == "rollback" and first_rollback:
                first_rollback = False
                await failure_barrier.pause()
            await rollback()

        async def paused_commit():
            await failure_barrier.pause()
            await commit()

        monkeypatch.setattr(db, "rollback", paused_rollback)
        if boundary == "commit":
            monkeypatch.setattr(db, "commit", paused_commit)
        return await original_failure(db, **kwargs)

    async def isolated_cancel(**kwargs):
        assert kwargs["metering"].event() == captured[0]
        await isolated_barrier.pause()
        await original_cancel(**kwargs)

    async def isolated_usage(event):
        assert event == captured[0]
        await isolated_barrier.pause()
        await original_usage(event)

    monkeypatch.setattr(execution, "consume_stream", failing_stream)
    monkeypatch.setattr(failure_module, "emit_failure_events", failure)
    monkeypatch.setattr(interruption, "finalize_cancelled_run", isolated_cancel)
    monkeypatch.setattr(interruption, "finalize_interrupted_usage", isolated_usage)
    monkeypatch.setattr(execution, "CANCEL_FINALIZE_TIMEOUT", 0.5)
    task = asyncio.create_task(
        run_scenario(committed_db_session_factory, context, model=scripted_model(turns=["Done."]))
    )
    try:
        await asyncio.wait_for(failure_barrier.reached.wait(), timeout=3)
        signal = AGENT_RUN_CANCEL_REQUEST if human_cancel else "shutdown"
        task.cancel(signal)
        await asyncio.wait_for(isolated_barrier.reached.wait(), timeout=1)
        task.cancel("repeated shutdown")
        if not settlement_blocked:
            isolated_barrier.release.set()
        with pytest.raises(asyncio.CancelledError) as cancelled:
            await asyncio.wait_for(task, timeout=2)
        assert cancelled.value.args == (signal,)
        assert rollback_owners and all(rollback_owners)
        assert not [t for t in asyncio.all_tasks() if t.get_name() == "agent-run-finalisation"]
    finally:
        failure_barrier.release.set()
        isolated_barrier.release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    [payload] = captured
    assert payload.requests == 1
    assert payload.input_tokens > 0
    async with committed_db_session_factory() as db:
        run = await db.get(AgentRun, context.run_id)
        if expected is not None:
            assert (run.status, run.error_code, run.error_message, run.completion_json) == expected
        else:
            assert run.status == (
                "cancelled" if human_cancel and not settlement_blocked else "running"
            )
        rows = list(
            await db.scalars(select(AIUsageEvent).where(AIUsageEvent.run_id == context.run_id))
        )
        assert len(rows) == (0 if settlement_blocked else 1)
    if settlement_blocked:
        assert any(
            record.message == "Agent run accounting incomplete"
            and record.invocation_id == payload.details["invocation_id"]
            and record.agent_run_id == str(context.run_id)
            and record.provider == payload.provider
            and record.model == payload.model
            and record.requests == payload.requests
            and record.input_tokens == payload.input_tokens
            for record in caplog.records
        )
    async with committed_db_session_factory() as db:
        assert await record_ai_usage_in_transaction(db, payload)
        assert await record_ai_usage_in_transaction(db, payload)
        await db.commit()
    async with committed_db_session_factory() as db:
        [row] = list(
            await db.scalars(select(AIUsageEvent).where(AIUsageEvent.run_id == context.run_id))
        )
        assert row.id == payload.event_id
        assert row.requests == payload.requests
