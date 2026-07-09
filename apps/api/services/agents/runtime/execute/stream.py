# apps/api/services/agents/runtime/execute/stream.py

"""Consume Pydantic AI stream events for execute_run."""

from collections.abc import AsyncIterable, Sequence
from typing import Any

from pydantic_ai import DeferredToolResults
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    NativeToolCallPart,
    NativeToolReturnPart,
)
from pydantic_ai.run import AgentRunResultEvent

from models.agent_run import AgentRun
from models.skills import Skill
from services.agents.runtime.approval_events import is_deferred_tool_resume_event
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.dispatch import record_native_tool_invocation_audit_event
from services.agents.runtime.events import EventTranslationState, emit_agent_stream_event
from services.agents.runtime.sinks import EventSink
from services.agents.runtime.skills import record_skill_activation


async def consume_stream(
    stream: AsyncIterable[Any],
    *,
    deps: RuntimeDeps,
    skills: Sequence[Skill],
    run: AgentRun,
    deferred_tool_results: DeferredToolResults | None,
    event_sink: EventSink,
) -> Any | None:
    terminal_result = None
    state = EventTranslationState()
    deferred_tool_call_ids = (
        set(deferred_tool_results.approvals) if deferred_tool_results is not None else set()
    )
    async for event in stream:
        if isinstance(event, AgentRunResultEvent):
            terminal_result = event.result
            continue
        if deferred_tool_results is not None and is_deferred_tool_resume_event(
            event,
            deferred_tool_call_ids=deferred_tool_call_ids,
        ):
            continue
        part = getattr(event, "part", None)
        if isinstance(part, NativeToolCallPart):
            state.native_tool_calls[part.tool_call_id] = part
        elif isinstance(part, NativeToolReturnPart):
            await record_native_tool_invocation_audit_event(
                deps=deps,
                call_part=state.native_tool_calls.pop(
                    part.tool_call_id,
                    None,
                ),
                return_part=part,
            )
        if (
            isinstance(event, FunctionToolCallEvent)
            and getattr(part, "tool_kind", None) == "capability-load"
        ):
            record_skill_activation(skills, part, run=run)
        await emit_agent_stream_event(
            event_sink,
            event,
            run_id=str(run.id),
            state=state,
        )
    return terminal_result
