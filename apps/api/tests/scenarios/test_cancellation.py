# apps/api/tests/scenarios/test_cancellation.py

"""User-requested cancellation at a live tool boundary."""

import asyncio
import importlib
from dataclasses import replace

import pytest
from pydantic_ai import ToolFailed, capture_run_messages
from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    RetryPromptPart,
    ToolCallPart,
    ToolReturnPart,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.database import set_session_tenant_context
from models.agent_run import AgentRun
from models.ai_usage_event import AIUsageEvent
from services.agent_runs import cancel_agent_run
from services.agents.runtime.cancellation import request_agent_run_task_cancel
from services.agents.runtime.persistence import load_message_history
from services.agents.runtime.sinks import CollectingSink
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from tests.support.delegation import scenario_effects
from tests.support.scenario import (
    ScenarioBarrier,
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    next_scenario_run,
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


@pytest.mark.parametrize("later_turn", [False, True])
async def test_mid_tool_cancel_persists_cancelled_without_failed_status(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    later_turn: bool,
) -> None:
    context = await build_scenario_agent(
        committed_db_session_factory,
        tool_names=["scenario_cancel_tool", "scenario_external_write"],
    )
    effects = []

    async def external_write(value: str = "ok") -> dict[str, bool]:
        effects.append(value)
        return {"ok": True}

    write_definition = RUNTIME_TOOL_CATALOG["scenario_external_write"]
    monkeypatch.setitem(
        RUNTIME_TOOL_CATALOG,
        write_definition.name,
        replace(write_definition, function=external_write),
    )
    if later_turn:
        previous = await run_scenario(
            committed_db_session_factory,
            context,
            model=scripted_model(
                turns=[
                    ToolTurn(
                        (ToolCall("scenario_external_write", {"value": "saved"}, "saved-effect"),)
                    ),
                    "Saved.",
                ]
            ),
        )
        assert previous.run.status == "completed"
        context = await next_scenario_run(committed_db_session_factory, context)
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
    with capture_run_messages() as captured:
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

    assert isinstance(captured[-1], ModelRequest)
    assert captured[-1].state == "interrupted"
    assert any(
        isinstance(part, ToolCallPart) and part.tool_call_id == "cancel-call"
        for message in captured
        for part in message.parts
    )
    assert (
        ModelMessagesTypeAdapter.validate_json(ModelMessagesTypeAdapter.dump_json(captured))
        == captured
    )

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
    async with committed_db_session_factory() as db:
        history = await load_message_history(db, conversation_id=context.conversation_id)
    assert (
        ModelMessagesTypeAdapter.validate_json(ModelMessagesTypeAdapter.dump_json(history))
        == history
    )
    calls = [
        part.tool_call_id
        for message in history
        for part in message.parts
        if isinstance(part, ToolCallPart)
    ]
    returns = [
        part.tool_call_id
        for message in history
        for part in message.parts
        if isinstance(part, ToolReturnPart | RetryPromptPart)
    ]
    assert set(calls) <= set(returns)
    if later_turn:
        assert calls.count("saved-effect") == returns.count("saved-effect") == 1
    subsequent = await next_scenario_run(committed_db_session_factory, context)
    seen_requests = []
    result = await run_scenario(
        committed_db_session_factory,
        subsequent,
        model=scripted_model(turns=["Continued."], seen_requests=seen_requests),
    )
    assert result.run.status == "completed"
    assert result.output == "Continued."
    assert invocations == 1
    assert effects == (["saved"] if later_turn else [])
    assert len(seen_requests) == 1
    async with committed_db_session_factory() as db:
        events = (
            await db.scalars(select(AIUsageEvent).where(AIUsageEvent.run_id == context.run_id))
        ).all()
    assert len(events) == 1
    assert events[0].requests == 1


@pytest.mark.parametrize("revocation", ["cancelled", "failed", "owner", "database"])
async def test_remote_revocation_prevents_pending_tool_side_effect(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    revocation: str,
) -> None:
    from uuid import uuid4

    from services.agent_runs.settle_run_family import settle_run_family
    from services.agents.runtime.execution_control import ExecutionInterruptedError

    with scenario_effects() as effects:
        context = await build_scenario_agent(
            committed_db_session_factory,
            tool_names=[effects.name],
        )
        barrier = ScenarioBarrier()
        durable_cancel_check = dispatch_module.check_execution_permission

        async def paused_cancel_check(deps):
            await barrier.pause()
            await durable_cancel_check(deps)

        monkeypatch.setattr(
            dispatch_module,
            "check_execution_permission",
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
                if revocation == "cancelled":
                    await cancel_agent_run(remote_db, run)
                elif revocation == "failed":
                    await settle_run_family(remote_db, run_id=run.id, error_code="run_abandoned")
                elif revocation == "owner":
                    run.owner_instance_id = str(uuid4())
                await remote_db.commit()

            if revocation == "database":

                async def unavailable(**_kwargs):
                    raise ConnectionError("Permission database unavailable")

                monkeypatch.setattr(
                    "services.agents.runtime.execution_control.read_execution_states", unavailable
                )

            barrier.release.set()
            with pytest.raises(
                asyncio.CancelledError if revocation == "cancelled" else ExecutionInterruptedError
            ):
                await task

            assert effects.calls == []
            async with committed_db_session_factory() as db:
                run = await db.get(AgentRun, context.run_id)
                assert run is not None
                assert (
                    run.status
                    == {
                        "cancelled": "cancelled",
                        "failed": "failed",
                        "owner": "running",
                        "database": "failed",
                    }[revocation]
                )


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
        assert run.status == ("cancelled" if human_cancel else "failed")
        if not human_cancel:
            assert run.error_code == "run_process_shutdown"
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
    original_stopped = interruption.finalize_stopped_run
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

    async def isolated_stopped(**kwargs):
        assert kwargs["metering"].event() == captured[0]
        await isolated_barrier.pause()
        await original_stopped(**kwargs)

    monkeypatch.setattr(execution, "consume_stream", failing_stream)
    monkeypatch.setattr(failure_module, "emit_failure_events", failure)
    monkeypatch.setattr(interruption, "finalize_cancelled_run", isolated_cancel)
    monkeypatch.setattr(interruption, "finalize_stopped_run", isolated_stopped)
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
                "running" if settlement_blocked else "cancelled" if human_cancel else "failed"
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


async def test_failed_first_tool_returns_valid_history_without_automatic_replay(
    committed_db_session_factory, monkeypatch
):
    context = await build_scenario_agent(
        committed_db_session_factory, tool_names=["scenario_cancel_tool"]
    )
    invocations = 0

    async def failed_tool(ctx):
        nonlocal invocations
        invocations += 1
        raise ToolFailed("The external service declined the request.")

    definition = RUNTIME_TOOL_CATALOG["scenario_cancel_tool"]
    monkeypatch.setitem(
        RUNTIME_TOOL_CATALOG, definition.name, replace(definition, function=failed_tool)
    )
    result = await run_scenario(
        committed_db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn((ToolCall("scenario_cancel_tool", {}, "failed-first"),)),
                "The request failed.",
            ]
        ),
    )
    assert result.run.status == "completed"
    [failed] = result.tool_returns("scenario_cancel_tool")
    assert failed["tool_call_id"] == "failed-first"
    assert failed["outcome"] == "failed"
    async with committed_db_session_factory() as db:
        history = await load_message_history(db, conversation_id=context.conversation_id)
    assert (
        ModelMessagesTypeAdapter.validate_json(ModelMessagesTypeAdapter.dump_json(history))
        == history
    )
    subsequent = await next_scenario_run(committed_db_session_factory, context)
    continued = await run_scenario(
        committed_db_session_factory, subsequent, model=scripted_model(turns=["Continued."])
    )
    assert continued.run.status == "completed"
    assert invocations == 1
    async with committed_db_session_factory() as db:
        events = (
            await db.scalars(select(AIUsageEvent).where(AIUsageEvent.run_id == context.run_id))
        ).all()
    assert len(events) == 1
    assert events[0].requests == 2


async def test_runtime_hooks_process_history_and_check_permission_before_effects(
    committed_db_session_factory, monkeypatch
):
    from pydantic_ai.models.function import FunctionModel

    from services.agents.runtime import capabilities
    from services.agents.runtime.history import HistoryTrimmer

    order = []
    original_trim = HistoryTrimmer.__call__
    original_model_permission = capabilities.check_execution_permission
    original_tool_permission = dispatch_module.check_execution_permission
    original_render = capabilities.render_untrusted_frames
    original_dispatch = capabilities.dispatch_tool_execution

    def trim(self, messages):
        order.append("history")
        return original_trim(self, messages)

    async def model_permission(deps):
        order.append("model-permission")
        await original_model_permission(deps)

    async def tool_permission(deps):
        order.append("tool-permission")
        await original_tool_permission(deps)

    def render(messages):
        order.append("frame")
        return original_render(messages)

    async def dispatch(*args, **kwargs):
        order.append("dispatch")
        return await original_dispatch(*args, **kwargs)

    async def external_write(value: str = "ok") -> dict[str, bool]:
        order.append("effect")
        return {"ok": True}

    monkeypatch.setattr(HistoryTrimmer, "__call__", trim)
    monkeypatch.setattr(capabilities, "check_execution_permission", model_permission)
    monkeypatch.setattr(dispatch_module, "check_execution_permission", tool_permission)
    monkeypatch.setattr(capabilities, "render_untrusted_frames", render)
    monkeypatch.setattr(capabilities, "dispatch_tool_execution", dispatch)
    definition = RUNTIME_TOOL_CATALOG["scenario_external_write"]
    monkeypatch.setitem(
        RUNTIME_TOOL_CATALOG, definition.name, replace(definition, function=external_write)
    )
    context = await build_scenario_agent(
        committed_db_session_factory, tool_names=["scenario_external_write"]
    )
    script = scripted_model(
        turns=[
            ToolTurn((ToolCall("scenario_external_write", {"value": "saved"}, "ordered-effect"),)),
            "Saved.",
        ]
    )

    async def stream(messages, info):
        order.append("model")
        async for chunk in script.stream_function(messages, info):
            yield chunk

    result = await run_scenario(
        committed_db_session_factory, context, model=FunctionModel(stream_function=stream)
    )
    assert result.run.status == "completed"
    assert order == [
        "history",
        "model-permission",
        "frame",
        "model",
        "dispatch",
        "tool-permission",
        "effect",
        "history",
        "model-permission",
        "frame",
        "model",
    ]
