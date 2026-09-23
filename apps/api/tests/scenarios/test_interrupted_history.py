"""Durable transcripts after budget exhaustion, cancellation, and approval failure."""

import asyncio
import importlib
from dataclasses import replace

import pytest
from pydantic_ai import DeferredToolResults, ToolApproved, ToolDenied, UsageLimitExceeded
from pydantic_ai.messages import ModelMessagesTypeAdapter, ToolCallPart, ToolReturnPart
from pydantic_ai.usage import RequestUsage
from sqlalchemy import select, text

from core.database import set_session_tenant_context
from models.agent_run import AgentRun
from models.conversation import ConversationMessage
from models.jobs import Job
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.cancellation import (
    AGENT_RUN_CANCEL_REQUEST,
    request_agent_run_task_cancel,
)
from services.agents.runtime.interrupted_history import INTERRUPTED_HISTORY_JOB_KIND
from services.agents.runtime.persistence import SYNTHESIZED_TOOL_RETURN_CONTENT
from services.agents.runtime.sinks import CollectingSink
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.jobs.handlers.persist_interrupted_history import persist_interrupted_history
from tests.support.scenario import (
    ScenarioBarrier,
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)


@pytest.mark.parametrize("interruption", ["token_limit", "cancelled"])
async def test_interrupted_run_persists_completed_and_unfinished_tool_calls(
    committed_db_session_factory, monkeypatch, interruption
):
    completed_count = 3 if interruption == "token_limit" else 2
    usage_estimates = iter([100] * completed_count + [10_000])
    monkeypatch.setattr(
        "pydantic_ai.models.function._estimate_usage",
        lambda _messages: RequestUsage(input_tokens=next(usage_estimates)),
    )
    context = await build_scenario_agent(
        committed_db_session_factory,
        tool_names=["scenario_external_write", "scenario_cancel_tool"],
        trigger="scheduled",
        metadata={
            "envelope": {"side_effect_policy": "allow"},
            "completion_contract": {
                "required": False,
                "criteria": [],
                "max_total_tokens": 1000,
            },
        },
    )
    effects = []

    async def external_write(value: str = "ok") -> dict[str, bool]:
        effects.append(value)
        return {"ok": True}

    write = RUNTIME_TOOL_CATALOG["scenario_external_write"]
    monkeypatch.setitem(RUNTIME_TOOL_CATALOG, write.name, replace(write, function=external_write))
    barrier = ScenarioBarrier()

    async def waiting_tool(ctx):
        await barrier.pause()
        return "released"

    waiting = RUNTIME_TOOL_CATALOG["scenario_cancel_tool"]
    monkeypatch.setitem(RUNTIME_TOOL_CATALOG, waiting.name, replace(waiting, function=waiting_tool))
    completed_ids = [f"completed-{index}" for index in range(completed_count)]
    turns = [
        ToolTurn((ToolCall(write.name, {"value": call_id}, call_id),)) for call_id in completed_ids
    ]
    turns.append(ToolTurn((ToolCall(waiting.name, {}, "unfinished"),)))
    if interruption == "token_limit":
        with pytest.raises(UsageLimitExceeded):
            await run_scenario(
                committed_db_session_factory, context, model=scripted_model(turns=turns)
            )
    else:
        # The waiting call must start before the operator stops the run.
        monkeypatch.setattr(
            "pydantic_ai.models.function._estimate_usage",
            lambda _messages: RequestUsage(input_tokens=100),
        )
        async with barrier.running(
            run_scenario(committed_db_session_factory, context, model=scripted_model(turns=turns))
        ) as task:
            await asyncio.wait_for(barrier.reached.wait(), timeout=3)
            request_agent_run_task_cancel(task, run_id=context.run_id)
            with pytest.raises(asyncio.CancelledError):
                await task

    assert effects == completed_ids
    async with committed_db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        run = await db.get(AgentRun, context.run_id)
        rows = list(
            await db.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == context.conversation_id)
                .order_by(ConversationMessage.sequence)
            )
        )
    assert run.status == ("failed" if interruption == "token_limit" else "cancelled")
    if interruption == "token_limit":
        assert run.outcome == "budget_exhausted"
    assert [row.sequence for row in rows] == list(range(1, len(rows) + 1))
    assert sum(row.role == "user" for row in rows) == 1
    assert all(row.metadata_json["agent_run_id"] == str(context.run_id) for row in rows)
    assert all(row.metadata_json["source"] == "pydantic_ai" for row in rows)
    # Read the stored parts directly so load-time repairs cannot hide missing rows.
    messages = ModelMessagesTypeAdapter.validate_python([row.parts for row in rows])
    calls = [
        part.tool_call_id
        for message in messages
        for part in message.parts
        if isinstance(part, ToolCallPart)
    ]
    returns = [
        part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)
    ]
    assert calls == [*completed_ids, "unfinished"]
    assert [part.tool_call_id for part in returns] == calls
    assert all(part.content == {"ok": True} for part in returns[:-1])
    assert returns[-1].content == SYNTHESIZED_TOOL_RETURN_CONTENT
    assert returns[-1].outcome == "interrupted"


async def test_failed_approval_continuation_keeps_real_return_and_decision_metadata(
    committed_db_session_factory, monkeypatch
):
    effects = []

    async def external_write(value: str = "ok") -> dict[str, bool]:
        effects.append(value)
        return {"ok": True}

    write = RUNTIME_TOOL_CATALOG["scenario_external_write"]
    monkeypatch.setitem(RUNTIME_TOOL_CATALOG, write.name, replace(write, function=external_write))
    context = await build_scenario_agent(
        committed_db_session_factory,
        tool_names=[write.name],
        tool_policies={write.name: "approval"},
    )
    suspended = await run_scenario(
        committed_db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(write.name, {"value": "original"}, "approved-write"),
                        ToolCall(write.name, {"value": "blocked"}, "denied-write"),
                    )
                )
            ]
        ),
    )
    assert suspended.run.status == "awaiting_approval"
    assert effects == []
    state = load_suspended_run_state(suspended.run)
    with pytest.raises(AssertionError, match="more requests than declared turns"):
        await run_scenario(
            committed_db_session_factory,
            context,
            model=scripted_model(turns=[]),
            prompt=None,
            expected_status="awaiting_approval",
            message_history=state.message_history,
            deferred_tool_results=DeferredToolResults(
                approvals={
                    "approved-write": ToolApproved(override_args={"value": "approved"}),
                    "denied-write": ToolDenied("The operator declined the write."),
                },
                metadata={"denied-write": {"reason": "The target is incorrect."}},
            ),
        )
    assert effects == ["approved"]
    async with committed_db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        run = await db.get(AgentRun, context.run_id)
        rows = list(
            await db.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == context.conversation_id)
                .order_by(ConversationMessage.sequence)
            )
        )
    assert run.status == "failed"
    assert sum(row.role == "user" for row in rows) == 1
    assert [row.id for row in rows[: len(suspended.messages)]] == [
        row.id for row in suspended.messages
    ]
    messages = ModelMessagesTypeAdapter.validate_python([row.parts for row in rows])
    calls = [
        part.tool_call_id
        for message in messages
        for part in message.parts
        if isinstance(part, ToolCallPart)
    ]
    returns = [
        part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)
    ]
    assert calls == ["approved-write", "denied-write"]
    assert sorted(part.tool_call_id for part in returns) == sorted(calls)
    approved = next(part for part in returns if part.tool_call_id == "approved-write")
    assert approved.content == {"ok": True}
    denied = next(part for part in returns if part.tool_call_id == "denied-write")
    assert denied.outcome == "denied"
    assert denied.content == "The operator declined the write."
    metadata = {
        call_id: value
        for row in rows
        for call_id, value in (row.metadata_json or {}).get("approval_results", {}).items()
    }
    assert metadata["approved-write"] == {
        "decision": "approved",
        "original_args": '{"value": "original"}',
        "effective_args": {"value": "approved"},
        "override_args": {"value": "approved"},
    }
    assert metadata["denied-write"]["decision"] == "denied"
    assert metadata["denied-write"]["reason"] == "The target is incorrect."


async def test_cancelled_approved_tool_persists_interrupted_return_without_repeating_call(
    committed_db_session_factory, monkeypatch
):
    barrier = ScenarioBarrier()
    invocations = []

    async def waiting_write(value: str = "ok") -> dict[str, bool]:
        invocations.append(value)
        await barrier.pause()
        return {"ok": True}

    write = RUNTIME_TOOL_CATALOG["scenario_external_write"]
    monkeypatch.setitem(RUNTIME_TOOL_CATALOG, write.name, replace(write, function=waiting_write))
    context = await build_scenario_agent(
        committed_db_session_factory,
        tool_names=[write.name],
        tool_policies={write.name: "approval"},
    )
    suspended = await run_scenario(
        committed_db_session_factory,
        context,
        model=scripted_model(
            turns=[ToolTurn((ToolCall(write.name, {"value": "original"}, "approved-write"),))]
        ),
    )
    assert suspended.run.status == "awaiting_approval"
    state = load_suspended_run_state(suspended.run)
    async with barrier.running(
        run_scenario(
            committed_db_session_factory,
            context,
            model=scripted_model(turns=[]),
            prompt=None,
            expected_status="awaiting_approval",
            message_history=state.message_history,
            deferred_tool_results=DeferredToolResults(
                approvals={"approved-write": ToolApproved(override_args={"value": "approved"})}
            ),
        )
    ) as task:
        await asyncio.wait_for(barrier.reached.wait(), timeout=3)
        request_agent_run_task_cancel(task, run_id=context.run_id)
        with pytest.raises(asyncio.CancelledError):
            await task

    assert invocations == ["approved"]
    async with committed_db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        run = await db.get(AgentRun, context.run_id)
        rows = list(
            await db.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == context.conversation_id)
                .order_by(ConversationMessage.sequence)
            )
        )
    assert run.status == "cancelled"
    messages = ModelMessagesTypeAdapter.validate_python([row.parts for row in rows])
    calls = [
        part.tool_call_id
        for message in messages
        for part in message.parts
        if isinstance(part, ToolCallPart)
    ]
    returns = [
        part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)
    ]
    assert calls == ["approved-write"]
    [interrupted] = returns
    assert interrupted.tool_call_id == "approved-write"
    assert interrupted.content == SYNTHESIZED_TOOL_RETURN_CONTENT
    assert interrupted.outcome == "interrupted"
    [return_row] = [row for row in rows if row.role == "tool"]
    assert return_row.metadata_json["approval_results"]["approved-write"] == {
        "decision": "approved",
        "original_args": '{"value": "original"}',
        "effective_args": {"value": "approved"},
        "override_args": {"value": "approved"},
    }


@pytest.mark.parametrize("human_cancel", [False, True])
async def test_cumulative_sql_timeout_queues_history_in_fresh_settlement_session(
    committed_db_session_factory, monkeypatch, human_cancel
):
    execution = importlib.import_module("services.agents.runtime.execute.execute_run")
    persistence = importlib.import_module("services.agents.runtime.persist_interrupted_messages")
    consume = execution.consume_stream
    persist = persistence.persist_new_messages
    queue = persistence._queue_history
    writing_sessions = []
    queue_sessions = []
    cancelled_queries = []

    async def interrupted_stream(*args, **kwargs):
        await consume(*args, **kwargs)
        if human_cancel:
            raise asyncio.CancelledError(AGENT_RUN_CANCEL_REQUEST)
        raise RuntimeError("Model stopped after producing a response")

    async def slow_sql_write(db, **kwargs):
        writing_sessions.append(db)
        await db.execute(text("SELECT pg_sleep(0.36)"))
        try:
            await db.execute(text("SELECT pg_sleep(0.44)"))
        except asyncio.CancelledError:
            cancelled_queries.append(True)
            raise
        return await persist(db, **kwargs)

    async def queued_history(db, **kwargs):
        queue_sessions.append(db)
        return await queue(db, **kwargs)

    monkeypatch.setattr(execution, "consume_stream", interrupted_stream)
    monkeypatch.setattr(execution, "CANCEL_FINALIZE_TIMEOUT", 1.2)
    monkeypatch.setattr(persistence, "persist_new_messages", slow_sql_write)
    monkeypatch.setattr(persistence, "_queue_history", queued_history)
    context = await build_scenario_agent(committed_db_session_factory)
    async with asyncio.timeout(2):
        with pytest.raises(asyncio.CancelledError if human_cancel else RuntimeError):
            await run_scenario(
                committed_db_session_factory,
                context,
                model=scripted_model(turns=["The response survives the interrupted transaction."]),
            )
    assert cancelled_queries == [True]
    assert len(writing_sessions) == len(queue_sessions) == 1
    assert writing_sessions[0] is not queue_sessions[0]
    monkeypatch.setattr(persistence, "persist_new_messages", persist)
    async with committed_db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        run = await db.get(AgentRun, context.run_id)
        assert run.status == ("cancelled" if human_cancel else "failed")
        [job] = list(
            await db.scalars(
                select(Job).where(
                    Job.kind == INTERRUPTED_HISTORY_JOB_KIND,
                    Job.subject_id == context.run_id,
                )
            )
        )
        assert job.workspace_id == context.workspace_id
        assert job.initiated_by_user_id == context.user_id
        before = list(
            await db.scalars(
                select(ConversationMessage).where(
                    ConversationMessage.conversation_id == context.conversation_id
                )
            )
        )
        assert [row.role for row in before] == ["user"]
        for _ in range(2):
            await persist_interrupted_history(db, job)
            await db.commit()
        rows = list(
            await db.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == context.conversation_id)
                .order_by(ConversationMessage.sequence)
            )
        )
        assert [row.role for row in rows] == ["user", "assistant"]
        assert rows[1].parts["parts"][0]["content"] == (
            "The response survives the interrupted transaction."
        )
        assert run.status == ("cancelled" if human_cancel else "failed")


async def test_failure_emitting_committed_success_does_not_repeat_transcript(
    committed_db_session_factory, monkeypatch
):
    context = await build_scenario_agent(committed_db_session_factory)
    sink = CollectingSink(run_id=context.run_id, conversation_id=context.conversation_id)
    emit = sink.emit
    failed = False

    async def fail_first_completed_status(payload):
        nonlocal failed
        if payload.event_name == "run.status" and payload.status == "completed" and not failed:
            failed = True
            raise RuntimeError("Stream disconnected after the result was saved")
        await emit(payload)

    monkeypatch.setattr(sink, "emit", fail_first_completed_status)
    with pytest.raises(RuntimeError, match="Stream disconnected"):
        await run_scenario(
            committed_db_session_factory,
            context,
            model=scripted_model(turns=["Saved result."]),
            sink=sink,
        )
    assert failed
    async with committed_db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        run = await db.get(AgentRun, context.run_id)
        rows = list(
            await db.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == context.conversation_id)
                .order_by(ConversationMessage.sequence)
            )
        )
    assert run.status == "completed"
    assert run.error_code is None
    assert [row.role for row in rows] == ["user", "assistant"]
    assert rows[1].parts["parts"][0]["content"] == "Saved result."
    assert sink.events[-1].data["status"] == "completed"
