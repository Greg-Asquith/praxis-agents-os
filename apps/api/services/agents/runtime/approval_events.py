# apps/api/services/agents/runtime/approval_events.py

"""Approval and deferred-tool stream event helpers."""

from collections.abc import Collection, Sequence
from typing import Any

from pydantic_ai import DeferredToolRequests, DeferredToolResults
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessage,
)
from pydantic_core import to_jsonable_python

from services.agents.runtime.events import (
    EVENT_TOOL_APPROVAL_REQUIRED,
    EVENT_TOOL_CALL,
    EVENT_TOOL_RESULT,
)
from services.agents.runtime.sinks import EventSink


def is_deferred_tool_resume_event(
    event: Any,
    *,
    deferred_tool_call_ids: Collection[str],
) -> bool:
    """Return true for raw deferred-tool events replaced by normalized replay."""
    if not isinstance(event, (FunctionToolCallEvent, FunctionToolResultEvent)):
        return False
    return getattr(event.part, "tool_call_id", None) in deferred_tool_call_ids


async def emit_approval_required_events(
    sink: EventSink,
    deferred_tool_requests: DeferredToolRequests,
) -> None:
    """Emit pending tool approvals to the client."""
    for approval in deferred_tool_requests.approvals:
        await sink.emit(
            EVENT_TOOL_APPROVAL_REQUIRED,
            {
                "tool_call_id": approval.tool_call_id,
                "name": approval.tool_name,
                "args": to_jsonable_python(approval.args),
            },
        )


async def emit_deferred_tool_resume_events(
    sink: EventSink,
    *,
    message_history: Sequence[ModelMessage],
    new_messages: Sequence[ModelMessage],
    deferred_tool_results: DeferredToolResults,
) -> None:
    """Replay executed deferred tools with approved override args when present."""
    deferred_tool_call_ids = set(deferred_tool_results.approvals)
    tool_calls = _tool_calls_by_id([*message_history, *new_messages])
    for message in new_messages:
        for part in getattr(message, "parts", []):
            if getattr(part, "part_kind", None) != "tool-return":
                continue
            tool_call_id = getattr(part, "tool_call_id", None)
            if tool_call_id is None or tool_call_id not in deferred_tool_call_ids:
                continue

            call = tool_calls.get(tool_call_id)
            if call is not None:
                await sink.emit(
                    EVENT_TOOL_CALL,
                    {
                        "tool_call_id": tool_call_id,
                        "name": call.tool_name,
                        "args": to_jsonable_python(
                            _effective_tool_args(
                                tool_call_id=tool_call_id,
                                original_args=call.args,
                                deferred_tool_results=deferred_tool_results,
                            )
                        ),
                    },
                )
            await sink.emit(
                EVENT_TOOL_RESULT,
                {
                    "tool_call_id": tool_call_id,
                    "name": getattr(part, "tool_name", None),
                    "result": to_jsonable_python(getattr(part, "content", None)),
                },
            )


def _tool_calls_by_id(messages: Sequence[ModelMessage]) -> dict[str, Any]:
    calls: dict[str, Any] = {}
    for message in messages:
        for part in getattr(message, "parts", []):
            if getattr(part, "part_kind", None) == "tool-call":
                calls[part.tool_call_id] = part
    return calls


def _effective_tool_args(
    *,
    tool_call_id: str,
    original_args: Any,
    deferred_tool_results: DeferredToolResults,
) -> Any:
    approval_result = deferred_tool_results.approvals.get(tool_call_id)
    override_args = getattr(approval_result, "override_args", None)
    return override_args if override_args is not None else original_args
