"""End-to-end AI usage ledger scenarios across terminal run paths."""

import asyncio

import pytest
from pydantic_ai import DeferredToolResults, ToolApproved
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.database import set_session_tenant_context
from models.agent_run import AgentRun
from models.ai_usage_event import AIUsageEvent
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.cancellation import request_agent_run_task_cancel
from services.agents.runtime.run_persistence import restored_run_usage
from tests.support.scenario import (
    ScenarioBarrier,
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)


async def _assert_run_usage_matches_ledger(session_factory, context, events, *, tool_calls):
    async with session_factory() as db:
        await set_session_tenant_context(db, workspace_id=context.workspace_id)
        run = await db.get(AgentRun, context.run_id)
        assert run is not None
        for column, counter in (
            ("input_tokens", "input_tokens"),
            ("input_tokens_cached", "cache_read_tokens"),
            ("output_tokens", "output_tokens"),
            ("requests", "requests"),
        ):
            total = sum(getattr(event, counter) for event in events)
            assert getattr(run, column) == run.usage_json[counter] == total
        assert run.usage_json["cache_write_tokens"] == sum(
            event.cache_write_tokens for event in events
        )
        assert run.tool_calls == run.usage_json["tool_calls"] == tool_calls


async def _events(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    workspace_id,
    run_id,
) -> list[AIUsageEvent]:
    async with session_factory() as db:
        await set_session_tenant_context(db, workspace_id=workspace_id)
        return list(
            (
                await db.scalars(
                    select(AIUsageEvent)
                    .where(AIUsageEvent.run_id == run_id)
                    .order_by(AIUsageEvent.occurred_at, AIUsageEvent.created_at)
                )
            ).all()
        )


async def test_success_records_one_logical_agent_invocation(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(db_session_factory)
    await run_scenario(
        db_session_factory,
        context,
        model=scripted_model(turns=["Done."]),
    )

    [event] = await _events(
        db_session_factory,
        workspace_id=context.workspace_id,
        run_id=context.run_id,
    )
    assert event.purpose == "agent_run"
    assert event.requests == 1
    assert event.agent_id == context.agent_id
    assert event.user_id == context.user_id


async def test_approval_resume_records_non_overlapping_invocations(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["scenario_external_write"],
        tool_policies={"scenario_external_write": "approval"},
    )
    model = scripted_model(
        turns=[
            ToolTurn((ToolCall("scenario_external_write", {"value": "ok"}, "write"),)),
            "Approved.",
        ]
    )
    suspended = await run_scenario(db_session_factory, context, model=model)
    assert suspended.run.status == RUN_STATUS_AWAITING_APPROVAL
    state = load_suspended_run_state(suspended.run)

    await run_scenario(
        db_session_factory,
        context,
        model=model,
        prompt=None,
        expected_status=RUN_STATUS_AWAITING_APPROVAL,
        message_history=state.message_history,
        deferred_tool_results=DeferredToolResults(
            approvals={state.pending_tool_call_ids[0]: ToolApproved()}
        ),
    )

    events = await _events(
        db_session_factory,
        workspace_id=context.workspace_id,
        run_id=context.run_id,
    )
    assert [event.requests for event in events] == [1, 1]


async def test_failed_run_records_completed_partial_request(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["scenario_bad_write"],
    )
    with pytest.raises(AssertionError, match="more requests"):
        await run_scenario(
            db_session_factory,
            context,
            model=scripted_model(
                turns=[ToolTurn((ToolCall("scenario_bad_write", {}, "bad-write"),))]
            ),
        )

    [event] = await _events(
        db_session_factory,
        workspace_id=context.workspace_id,
        run_id=context.run_id,
    )
    assert event.purpose == "agent_run"
    assert event.requests == 2
    assert event.details["usage_source"] == "accumulator_delta"
    await _assert_run_usage_matches_ledger(db_session_factory, context, [event], tool_calls=1)


async def test_failed_approval_resume_excludes_persisted_baseline(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await build_scenario_agent(
        db_session_factory,
        tool_names=["scenario_external_write"],
        tool_policies={"scenario_external_write": "approval"},
    )
    model = scripted_model(
        turns=[
            ToolTurn((ToolCall("scenario_external_write", {"value": "ok"}, "write"),)),
        ]
    )
    suspended = await run_scenario(db_session_factory, context, model=model)
    state = load_suspended_run_state(suspended.run)

    with pytest.raises(AssertionError, match="more requests"):
        await run_scenario(
            db_session_factory,
            context,
            model=model,
            prompt=None,
            expected_status=RUN_STATUS_AWAITING_APPROVAL,
            message_history=state.message_history,
            deferred_tool_results=DeferredToolResults(
                approvals={state.pending_tool_call_ids[0]: ToolApproved()}
            ),
            usage=restored_run_usage(suspended.run),
        )

    events = await _events(
        db_session_factory,
        workspace_id=context.workspace_id,
        run_id=context.run_id,
    )
    assert [event.requests for event in events] == [1, 1]
    await _assert_run_usage_matches_ledger(db_session_factory, context, events, tool_calls=1)


@pytest.mark.parametrize("resume", [False, True])
async def test_cancelled_stream_records_usage_after_last_checkpoint(
    committed_db_session_factory, monkeypatch, resume
):
    monkeypatch.setattr(
        "pydantic_ai.models.function._estimate_usage",
        lambda _messages: RequestUsage(
            input_tokens=100, cache_read_tokens=20, cache_write_tokens=10, output_tokens=5
        ),
    )
    context = await build_scenario_agent(
        committed_db_session_factory,
        tool_names=["scenario_external_write"],
        tool_policies={"scenario_external_write": "approval"},
    )
    continuation = {}
    if resume:
        suspended = await run_scenario(
            committed_db_session_factory,
            context,
            model=scripted_model(
                turns=[ToolTurn((ToolCall("scenario_external_write", {"value": "ok"}, "write"),))]
            ),
        )
        state = load_suspended_run_state(suspended.run)
        continuation = {
            "prompt": None,
            "expected_status": RUN_STATUS_AWAITING_APPROVAL,
            "message_history": state.message_history,
            "deferred_tool_results": DeferredToolResults(approvals={"write": ToolApproved()}),
            "usage": restored_run_usage(suspended.run),
        }
    barrier = ScenarioBarrier()

    async def partial_stream(_messages, _info):
        yield "Partial response."
        await barrier.pause()

    async with barrier.running(
        run_scenario(
            committed_db_session_factory,
            context,
            model=FunctionModel(stream_function=partial_stream),
            **continuation,
        )
    ) as task:
        await asyncio.wait_for(barrier.reached.wait(), timeout=3)
        request_agent_run_task_cancel(task, run_id=context.run_id)
        with pytest.raises(asyncio.CancelledError):
            await task

    events = await _events(
        committed_db_session_factory,
        workspace_id=context.workspace_id,
        run_id=context.run_id,
    )
    assert [event.requests for event in events] == ([1, 1] if resume else [1])
    assert all(event.input_tokens == 100 and event.cache_read_tokens == 20 for event in events)
    await _assert_run_usage_matches_ledger(
        committed_db_session_factory, context, events, tool_calls=int(resume)
    )


@pytest.mark.parametrize("sink_state", ["closed", "detached"])
async def test_unavailable_stream_does_not_prevent_usage_settlement(
    committed_db_session_factory, sink_state
):
    from services.agents.runtime.execute_run import execute_run
    from services.agents.runtime.sinks import StreamSink

    context = await build_scenario_agent(committed_db_session_factory)
    sink = StreamSink(run_id=context.run_id, conversation_id=context.conversation_id)
    if sink_state == "closed":
        await sink.close()
    else:
        sink.detach()
    async with committed_db_session_factory() as db:
        result = await execute_run(
            db,
            conversation_id=context.conversation_id,
            run_id=context.run_id,
            user_prompt="Reply.",
            model=scripted_model(turns=["Done."]),
            sink=sink,
        )
    assert result.run.status == "completed"
    [event] = await _events(
        committed_db_session_factory, workspace_id=context.workspace_id, run_id=context.run_id
    )
    assert event.requests == 1
