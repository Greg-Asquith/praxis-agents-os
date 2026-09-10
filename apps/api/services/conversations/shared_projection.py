# apps/api/services/conversations/shared_projection.py

"""Keeps the normal transcript contract without approval execution state."""

from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.conversation import Conversation, ConversationMessage
from services.conversations.schemas import ConversationMessageRead

_MISSING_ARGS = object()

_CALL_PARTS = {"tool-call", "builtin-tool-call", "native-tool-call"}
_RETURN_PARTS = {"tool-return", "builtin-tool-return", "native-tool-return"}
_TOOL_PARTS = _CALL_PARTS | _RETURN_PARTS
_DISPLAY_PARTS = {"text", "user-prompt"} | _TOOL_PARTS
_PENDING_STATUSES = {"awaiting_approval", "pending"}
_PART_FIELDS = frozenset(
    {
        "part_kind",
        "content",
        "tool_name",
        "tool_kind",
        "tool_call_id",
        "args",
        "outcome",
        "timestamp",
    }
)


async def load_completed_tool_calls(
    db: AsyncSession, *, conversation: Conversation, messages: Sequence[ConversationMessage]
) -> dict[tuple[str, str], Any]:
    """Resolves completed display arguments across transcript page boundaries."""
    call_ids = {
        part["tool_call_id"]
        for message in messages
        for part in message.parts.get("parts", [])
        if isinstance(part, dict)
        and part.get("part_kind") in _TOOL_PARTS
        and isinstance(part.get("tool_call_id"), str)
    }
    if not call_ids:
        return {}
    rows = await db.execute(
        select(ConversationMessage.parts, ConversationMessage.metadata_json).where(
            ConversationMessage.workspace_id == conversation.workspace_id,
            ConversationMessage.conversation_id == conversation.id,
            ConversationMessage.deleted == False,  # noqa: E712
            or_(
                *[
                    ConversationMessage.parts.contains({"parts": [{"tool_call_id": call_id}]})
                    for call_id in call_ids
                ]
            ),
        )
    )
    return _completed_display_args(rows)


def _completed_display_args(
    rows: Iterable[tuple[dict[str, Any], dict[str, Any] | None]],
) -> dict[tuple[str, str], Any]:
    original = {}
    completed = {}
    for payload, metadata in rows:
        metadata = metadata or {}
        approvals = metadata.get("approval_results")
        approvals = approvals if isinstance(approvals, dict) else {}
        for part in payload.get("parts", []):
            if not isinstance(part, dict):
                continue
            call_id = part.get("tool_call_id")
            key = (metadata.get("agent_run_id", ""), call_id)
            if part.get("part_kind") in _CALL_PARTS:
                original[key] = part.get("args")
            elif (
                part.get("part_kind") in _RETURN_PARTS
                and part.get("status") not in _PENDING_STATUSES
            ):
                approval = approvals.get(call_id)
                completed[key] = (
                    approval.get("effective_args", _MISSING_ARGS)
                    if isinstance(approval, dict)
                    else _MISSING_ARGS
                )
    return {
        key: original.get(key, _MISSING_ARGS) if args is _MISSING_ARGS else args
        for key, args in completed.items()
    }


def project_shared_message(
    message: ConversationMessage, *, completed_calls: dict[tuple[str, str], Any] | None = None
) -> ConversationMessageRead:
    """Returns ordinary saved display parts without model or approval metadata."""
    saved_parts = message.parts.get("parts")
    parts = saved_parts if isinstance(saved_parts, list) else []
    metadata = message.metadata_json or {}
    run_id = metadata.get("agent_run_id", "")
    completed = completed_calls
    if completed is None:
        completed = _completed_display_args([({"parts": parts}, message.metadata_json)])
    visible = []
    for part in parts if message.role != "system" else []:
        if not isinstance(part, dict) or part.get("part_kind") not in _DISPLAY_PARTS:
            continue
        if part.get("status") in _PENDING_STATUSES:
            continue
        key = (run_id, part.get("tool_call_id"))
        if part.get("part_kind") in _CALL_PARTS and key not in completed:
            continue
        visible.append(_display_part(part, completed.get(key, _MISSING_ARGS)))
    return ConversationMessageRead(
        id=message.id,
        conversation_id=message.conversation_id,
        role=message.role,
        parts={"parts": visible},
        metadata_json={"agent_run_id": metadata["agent_run_id"]}
        if isinstance(metadata.get("agent_run_id"), str)
        else None,
        sequence=message.sequence,
        created_at=message.created_at,
        updated_at=message.updated_at,
    )


def _display_part(part: dict[str, Any], completed_args: Any) -> dict[str, Any]:
    visible = {key: value for key, value in part.items() if key in _PART_FIELDS}
    if part.get("part_kind") == "user-prompt" and isinstance(part.get("content"), list):
        visible["content"] = [
            {key: item[key] for key in ("kind", "identifier", "media_type") if key in item}
            if isinstance(item, dict) and item.get("kind") == "binary"
            else item
            for item in part["content"]
        ]
    if completed_args is not _MISSING_ARGS and part.get("part_kind") in _TOOL_PARTS:
        visible["args"] = completed_args
    metadata = part.get("metadata")
    if isinstance(metadata, dict):
        display_metadata = {}
        if "public_result" in metadata:
            display_metadata["public_result"] = metadata["public_result"]
        trace = metadata.get("code_mode_trace")
        if isinstance(trace, dict) and isinstance(trace.get("calls"), list):
            display_metadata["code_mode_trace"] = {
                "calls": [
                    {
                        key: child[key]
                        for key in (
                            "tool_call_id",
                            "tool_name",
                            "status",
                            "presentation_result",
                            "excerpt",
                        )
                        if key in child
                    }
                    for child in trace["calls"]
                    if isinstance(child, dict) and child.get("status") not in _PENDING_STATUSES
                ],
                "output_excerpt": trace.get("output_excerpt"),
            }
        if display_metadata:
            visible["metadata"] = display_metadata
    return visible
