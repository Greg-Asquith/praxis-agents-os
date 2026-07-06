# apps/api/services/agents/runtime/approval_events.py

"""Approval and deferred-tool stream event helpers."""

from collections.abc import Collection, Sequence
from typing import Any

from pydantic_ai import (
    DeferredToolRequests,
    DeferredToolResults,
    ToolApproved,
    ToolDenied,
)
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessage,
)
from pydantic_core import to_jsonable_python

from services.agents.delegation_approval import (
    DELEGATED_APPROVAL_CHILD_AGENT_ID_KEY,
    DELEGATED_APPROVAL_CHILD_AGENT_NAME_KEY,
    DELEGATED_APPROVAL_CHILD_CONVERSATION_ID_KEY,
    DELEGATED_APPROVAL_CHILD_RUN_ID_KEY,
    DELEGATED_APPROVAL_KIND,
    DELEGATED_APPROVAL_KIND_KEY,
    DELEGATED_APPROVAL_PENDING_APPROVALS_KEY,
)
from services.agents.runtime.events import (
    EVENT_TOOL_APPROVAL_REQUIRED,
    EVENT_TOOL_CALL,
    EVENT_TOOL_RESULT,
)
from services.agents.runtime.sinks import EventSink
from services.agents.runtime.staged_tool_content import tool_args_for_display


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
        metadata = deferred_tool_requests.metadata.get(approval.tool_call_id)
        delegated_approvals = _delegated_pending_approvals(
            metadata,
            parent_tool_call_id=approval.tool_call_id,
        )
        if delegated_approvals is not None:
            for delegated_approval in delegated_approvals:
                await sink.emit(EVENT_TOOL_APPROVAL_REQUIRED, delegated_approval)
            continue

        await sink.emit(
            EVENT_TOOL_APPROVAL_REQUIRED,
            {
                "tool_call_id": approval.tool_call_id,
                "name": approval.tool_name,
                "args": to_jsonable_python(
                    tool_args_for_display(
                        tool_name=approval.tool_name,
                        args=approval.args,
                        metadata=metadata,
                    )
                ),
            },
        )


def _delegated_pending_approvals(
    metadata: dict[str, Any] | None,
    *,
    parent_tool_call_id: str,
) -> list[dict[str, Any]] | None:
    if not isinstance(metadata, dict):
        return None
    if metadata.get(DELEGATED_APPROVAL_KIND_KEY) != DELEGATED_APPROVAL_KIND:
        return None
    pending_approvals = metadata.get(DELEGATED_APPROVAL_PENDING_APPROVALS_KEY)
    if not isinstance(pending_approvals, list):
        return None

    delegation = _delegated_approval_projection(
        metadata,
        parent_tool_call_id=parent_tool_call_id,
        pending_approval_count=len(pending_approvals),
    )
    approvals: list[dict[str, Any]] = []
    for pending_approval in pending_approvals:
        if not isinstance(pending_approval, dict):
            return None
        tool_call_id = pending_approval.get("tool_call_id")
        name = pending_approval.get("name")
        if not isinstance(tool_call_id, str) or not isinstance(name, str):
            return None
        approvals.append(
            {
                "tool_call_id": tool_call_id,
                "name": name,
                "args": tool_args_for_display(
                    tool_name=name,
                    args=pending_approval.get("args"),
                    metadata=(
                        pending_approval.get("metadata")
                        if isinstance(pending_approval.get("metadata"), dict)
                        else None
                    ),
                ),
                "delegation": delegation,
            }
        )
    return approvals


def _delegated_approval_projection(
    metadata: dict[str, Any],
    *,
    parent_tool_call_id: str,
    pending_approval_count: int,
) -> dict[str, Any] | None:
    child_agent_id = metadata.get(DELEGATED_APPROVAL_CHILD_AGENT_ID_KEY)
    child_agent_name = metadata.get(DELEGATED_APPROVAL_CHILD_AGENT_NAME_KEY)
    child_conversation_id = metadata.get(DELEGATED_APPROVAL_CHILD_CONVERSATION_ID_KEY)
    child_run_id = metadata.get(DELEGATED_APPROVAL_CHILD_RUN_ID_KEY)
    if not (
        isinstance(child_agent_id, str)
        and isinstance(child_agent_name, str)
        and isinstance(child_conversation_id, str)
        and isinstance(child_run_id, str)
    ):
        return None

    return {
        "parent_tool_call_id": parent_tool_call_id,
        "child_agent_id": child_agent_id,
        "child_agent_name": child_agent_name,
        "child_conversation_id": child_conversation_id,
        "child_run_id": child_run_id,
        "pending_approval_count": pending_approval_count,
    }


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
                            tool_args_for_display(
                                tool_name=call.tool_name,
                                args=_effective_tool_args(
                                    tool_call_id=tool_call_id,
                                    original_args=call.args,
                                    deferred_tool_results=deferred_tool_results,
                                ),
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


def build_deferred_tool_result_metadata(
    *,
    message_history: Sequence[ModelMessage],
    new_messages: Sequence[ModelMessage],
    deferred_tool_results: DeferredToolResults,
) -> dict[str, dict[str, Any]]:
    """Return display metadata for persisted approved/denied tool results."""
    tool_return_ids = _tool_return_ids(new_messages)
    if not tool_return_ids:
        return {}

    tool_calls = _tool_calls_by_id([*message_history, *new_messages])
    metadata: dict[str, dict[str, Any]] = {}

    for tool_call_id, approval_result in deferred_tool_results.approvals.items():
        if tool_call_id not in tool_return_ids:
            continue

        call = tool_calls.get(tool_call_id)
        override_args = getattr(approval_result, "override_args", None)
        effective_args = (
            _effective_tool_args(
                tool_call_id=tool_call_id,
                original_args=call.args,
                deferred_tool_results=deferred_tool_results,
            )
            if call is not None
            else override_args
        )
        result_metadata: dict[str, Any] = {
            "decision": _decision_for_approval_result(approval_result),
        }

        if call is not None:
            result_metadata["original_args"] = to_jsonable_python(
                tool_args_for_display(tool_name=call.tool_name, args=call.args)
            )
        if call is not None or override_args is not None:
            result_metadata["effective_args"] = to_jsonable_python(
                tool_args_for_display(
                    tool_name=call.tool_name if call is not None else "",
                    args=effective_args,
                )
            )
        if isinstance(approval_result, ToolApproved) and override_args is not None:
            result_metadata["override_args"] = to_jsonable_python(
                tool_args_for_display(
                    tool_name=call.tool_name if call is not None else "",
                    args=override_args,
                )
            )
        if isinstance(approval_result, ToolDenied):
            result_metadata["message"] = approval_result.message

        metadata[tool_call_id] = result_metadata

    return metadata


def _tool_calls_by_id(messages: Sequence[ModelMessage]) -> dict[str, Any]:
    calls: dict[str, Any] = {}
    for message in messages:
        for part in getattr(message, "parts", []):
            if getattr(part, "part_kind", None) == "tool-call":
                calls[part.tool_call_id] = part
    return calls


def _tool_return_ids(messages: Sequence[ModelMessage]) -> set[str]:
    tool_return_ids: set[str] = set()
    for message in messages:
        for part in getattr(message, "parts", []):
            if getattr(part, "part_kind", None) != "tool-return":
                continue
            tool_call_id = getattr(part, "tool_call_id", None)
            if tool_call_id is not None:
                tool_return_ids.add(tool_call_id)
    return tool_return_ids


def _effective_tool_args(
    *,
    tool_call_id: str,
    original_args: Any,
    deferred_tool_results: DeferredToolResults,
) -> Any:
    approval_result = deferred_tool_results.approvals.get(tool_call_id)
    override_args = getattr(approval_result, "override_args", None)
    return override_args if override_args is not None else original_args


def _decision_for_approval_result(approval_result: Any) -> str:
    if isinstance(approval_result, ToolDenied):
        return "denied"
    return "approved"
