# apps/api/tests/scenarios/test_suspension_finalisation.py

"""A committed approval suspension survives failures and cancels that follow it."""

import asyncio
import importlib

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL
from services.agents.runtime.approval_state import APPROVAL_STATE_METADATA_KEY
from services.agents.runtime.cancellation import request_agent_run_task_cancel
from services.agents.runtime.events import EVENT_DONE
from services.agents.runtime.sinks import CollectingSink
from tests.support.scenario import (
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)

pytestmark = pytest.mark.asyncio

finalize_module = importlib.import_module("services.agents.runtime.execute.finalize")


async def _approval_context(session_factory: async_sessionmaker[AsyncSession]):
    context = await build_scenario_agent(
        session_factory,
        tool_names=["scenario_external_write"],
        tool_policies={"scenario_external_write": "approval"},
    )
    model = scripted_model(
        turns=[ToolTurn((ToolCall("scenario_external_write", {"value": ""}, "approval-call"),))]
    )
    return context, model


async def test_failure_after_suspension_commit_keeps_the_approval_request(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context, model = await _approval_context(db_session_factory)
    real_emit = finalize_module.emit_final_events
    calls = 0

    async def announce_fails_once(event_sink, run):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("stream announce failed")
        await real_emit(event_sink, run)

    monkeypatch.setattr(finalize_module, "emit_final_events", announce_fails_once)

    result = await run_scenario(db_session_factory, context, model=model)

    assert result.run.status == RUN_STATUS_AWAITING_APPROVAL
    assert APPROVAL_STATE_METADATA_KEY in result.run.metadata_json
    done = [event for event in result.events if event.event == EVENT_DONE]
    assert [event.data["status"] for event in done] == [RUN_STATUS_AWAITING_APPROVAL]


class _CancelOnDoneSink(CollectingSink):
    """Delivers a person's Stop while the suspension's final events are being sent."""

    async def emit(self, payload) -> None:
        await super().emit(payload)
        if payload.event_name == EVENT_DONE:
            request_agent_run_task_cancel(asyncio.current_task(), run_id=self.run_id)
            await asyncio.sleep(0)


async def test_cancel_after_suspension_announce_sends_one_final_pair(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context, model = await _approval_context(db_session_factory)
    sink = _CancelOnDoneSink(run_id=context.run_id, conversation_id=context.conversation_id)

    with pytest.raises(asyncio.CancelledError):
        await asyncio.create_task(run_scenario(db_session_factory, context, model=model, sink=sink))

    done = [event for event in sink.events if event.event == EVENT_DONE]
    assert [event.data["status"] for event in done] == [RUN_STATUS_AWAITING_APPROVAL]
    assert sink.events[-1].event == EVENT_DONE
