# apps/api/services/agents/runtime/persistence.py

"""Round-trip Pydantic AI messages through ConversationMessage rows."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic_ai import DeferredToolResults, ToolDenied
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ToolCallPart,
    ToolReturnPart,
    UserContent,
    UserPromptPart,
)
from sqlalchemy import func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.conversation import Conversation, ConversationMessage

PYDANTIC_AI_MESSAGE_SOURCE = "pydantic_ai"
_CAPABILITY_LOAD_TOOL_KIND = "capability-load"


async def load_message_history(
    db: AsyncSession,
    *,
    conversation_id: UUID,
) -> list[ModelMessage]:
    """Load persisted Pydantic AI history for a conversation."""
    if settings.AGENT_HISTORY_MAX_TURNS is None:
        return await _load_full_message_history(db, conversation_id=conversation_id)

    rows = await _load_windowed_message_rows(
        db,
        conversation_id=conversation_id,
        limit=settings.AGENT_HISTORY_DB_MAX_MESSAGES,
    )
    return _messages_from_rows(rows)


async def _load_full_message_history(
    db: AsyncSession,
    *,
    conversation_id: UUID,
) -> list[ModelMessage]:
    """Load all persisted Pydantic AI history for a conversation."""
    rows = await db.scalars(
        select(ConversationMessage)
        .where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.deleted == False,  # noqa: E712
        )
        .order_by(ConversationMessage.sequence)
    )
    stored_rows = [
        row for row in rows if (row.metadata_json or {}).get("source") == PYDANTIC_AI_MESSAGE_SOURCE
    ]
    return _messages_from_rows(stored_rows)


async def load_message_history_span(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    start_sequence: int | None = None,
    end_sequence: int | None = None,
) -> list[ModelMessage]:
    """Load one persisted Pydantic AI message span by stable sequence bounds."""
    stmt = (
        select(ConversationMessage)
        .where(*_pydantic_message_filters(conversation_id))
        .order_by(ConversationMessage.sequence)
    )
    if start_sequence is not None:
        stmt = stmt.where(ConversationMessage.sequence >= start_sequence)
    if end_sequence is not None:
        stmt = stmt.where(ConversationMessage.sequence < end_sequence)
    return _messages_from_rows(list((await db.scalars(stmt)).all()))


def _messages_from_rows(rows: Sequence[ConversationMessage]) -> list[ModelMessage]:
    if not rows:
        return []
    return list(ModelMessagesTypeAdapter.validate_python([row.parts for row in rows]))


async def load_history_watermark_keys(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    limit: int,
    exclude_run_id: UUID | None = None,
) -> tuple[UUID, ...]:
    """Load stable ids for the most recent clean persisted user boundaries."""
    if limit <= 0:
        return ()
    stmt = (
        select(ConversationMessage.id)
        .where(
            *_pydantic_message_filters(conversation_id),
            ConversationMessage.parts.op("@>")({"parts": [{"part_kind": "user-prompt"}]}),
            not_(ConversationMessage.parts.op("@>")({"parts": [{"part_kind": "tool-return"}]})),
            not_(ConversationMessage.parts.op("@>")({"parts": [{"part_kind": "retry-prompt"}]})),
        )
        .order_by(ConversationMessage.sequence.desc())
        .limit(limit)
    )
    if exclude_run_id is not None:
        stmt = stmt.where(
            ConversationMessage.metadata_json["agent_run_id"].astext != str(exclude_run_id)
        )
    keys = list((await db.scalars(stmt)).all())
    keys.reverse()
    return tuple(keys)


async def _load_windowed_message_rows(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    limit: int,
) -> list[ConversationMessage]:
    base_filters = _pydantic_message_filters(conversation_id)
    window_ids = (
        select(ConversationMessage.id)
        .where(*base_filters)
        .order_by(ConversationMessage.sequence.desc())
        .limit(limit)
        .subquery()
    )
    window_rows = (
        await db.scalars(
            select(ConversationMessage)
            .join(window_ids, ConversationMessage.id == window_ids.c.id)
            .order_by(ConversationMessage.sequence)
        )
    ).all()
    if len(window_rows) < limit:
        return list(window_rows)

    lowest_window_sequence = window_rows[0].sequence
    backfill_rows = (
        await db.scalars(
            select(ConversationMessage)
            .where(
                *base_filters,
                ConversationMessage.sequence < lowest_window_sequence,
                _capability_load_filter(),
            )
            .order_by(ConversationMessage.sequence)
        )
    ).all()
    return [*backfill_rows, *window_rows]


def _pydantic_message_filters(conversation_id: UUID):
    return (
        ConversationMessage.conversation_id == conversation_id,
        ConversationMessage.deleted == False,  # noqa: E712
        ConversationMessage.metadata_json["source"].astext == PYDANTIC_AI_MESSAGE_SOURCE,
    )


def _capability_load_filter():
    return or_(
        ConversationMessage.parts.op("@>")(
            {
                "parts": [
                    {
                        "part_kind": "tool-call",
                        "tool_kind": _CAPABILITY_LOAD_TOOL_KIND,
                    }
                ]
            }
        ),
        ConversationMessage.parts.op("@>")(
            {
                "parts": [
                    {
                        "part_kind": "tool-return",
                        "tool_kind": _CAPABILITY_LOAD_TOOL_KIND,
                    }
                ]
            }
        ),
    )


async def persist_new_messages(
    db: AsyncSession,
    *,
    conversation: Conversation,
    run_id: UUID,
    messages: Sequence[ModelMessage],
    client_message_id: str | None = None,
    tool_approval_metadata_by_call_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[ConversationMessage]:
    """Append newly produced Pydantic AI messages to a conversation."""
    serialized = _dump_messages(messages)
    if not serialized:
        return []

    next_sequence = await _next_sequence(db, conversation_id=conversation.id)
    now = datetime.now(UTC)
    rows: list[ConversationMessage] = []
    user_client_message_id = client_message_id
    for index, message in enumerate(serialized):
        role = _role_for_message(message)
        row_client_message_id = None
        if user_client_message_id is not None and role == "user":
            row_client_message_id = user_client_message_id
            user_client_message_id = None
        metadata = {
            "source": PYDANTIC_AI_MESSAGE_SOURCE,
            "agent_run_id": str(run_id),
            "pydantic_kind": message.get("kind"),
        }
        approval_results = _tool_approval_metadata_for_message(
            message,
            tool_approval_metadata_by_call_id,
        )
        if approval_results:
            metadata["approval_results"] = approval_results
        row = ConversationMessage(
            conversation_id=conversation.id,
            workspace_id=conversation.workspace_id,
            role=role,
            parts=message,
            metadata_json=metadata,
            tool_name=_first_tool_name(message),
            sequence=next_sequence + index,
            client_message_id=row_client_message_id,
        )
        db.add(row)
        rows.append(row)

    conversation.last_message_at = now
    await db.flush()
    return rows


async def persist_eager_user_prompt(
    db: AsyncSession,
    *,
    conversation: Conversation,
    run_id: UUID,
    user_prompt: str | Sequence[UserContent] | None,
    client_message_id: str | None,
) -> list[ConversationMessage]:
    """Persist the current turn's user prompt before provider streaming starts."""
    if user_prompt is None:
        return []
    return await persist_new_messages(
        db,
        conversation=conversation,
        run_id=run_id,
        messages=[ModelRequest(parts=[UserPromptPart(user_prompt)])],
        client_message_id=client_message_id,
    )


async def persist_eager_denied_tool_results(
    db: AsyncSession,
    *,
    conversation: Conversation,
    run_id: UUID,
    message_history: Sequence[ModelMessage],
    deferred_tool_results: DeferredToolResults | None,
) -> set[str]:
    """Persist denied tool returns before the provider continuation starts."""
    if deferred_tool_results is None:
        return set()

    calls_by_id = {
        part.tool_call_id: part
        for message in message_history
        for part in message.parts
        if isinstance(part, ToolCallPart)
    }
    denied_parts: list[ToolReturnPart] = []
    for tool_call_id, result in deferred_tool_results.approvals.items():
        if not isinstance(result, ToolDenied):
            continue
        call = calls_by_id.get(tool_call_id)
        if call is None:
            continue
        denied_parts.append(
            ToolReturnPart(
                tool_name=call.tool_name,
                content=result.message,
                tool_call_id=tool_call_id,
                outcome="denied",
            )
        )

    if not denied_parts:
        return set()

    message = ModelRequest(parts=denied_parts)
    from services.agents.runtime.approval_events import build_deferred_tool_result_metadata

    metadata = build_deferred_tool_result_metadata(
        message_history=message_history,
        new_messages=[message],
        deferred_tool_results=deferred_tool_results,
    )
    await persist_new_messages(
        db,
        conversation=conversation,
        run_id=run_id,
        messages=[message],
        tool_approval_metadata_by_call_id=metadata,
    )
    return {part.tool_call_id for part in denied_parts}


def without_initial_user_prompt(messages: Sequence[ModelMessage]) -> list[ModelMessage]:
    """Drop the first current-run user prompt already written by eager persistence."""
    pending = list(messages)
    if pending and _is_user_prompt_request(pending[0]):
        return pending[1:]
    return pending


def without_tool_returns(
    messages: Sequence[ModelMessage],
    *,
    tool_call_ids: set[str],
) -> list[ModelMessage]:
    """Drop tool returns that were already durably persisted before streaming."""
    if not tool_call_ids:
        return list(messages)

    filtered: list[ModelMessage] = []
    for message in messages:
        if not isinstance(message, ModelRequest):
            filtered.append(message)
            continue
        parts = [
            part
            for part in message.parts
            if not (isinstance(part, ToolReturnPart) and part.tool_call_id in tool_call_ids)
        ]
        if parts:
            filtered.append(replace(message, parts=parts))
    return filtered


def _dump_messages(messages: Sequence[ModelMessage]) -> list[dict[str, Any]]:
    return json.loads(ModelMessagesTypeAdapter.dump_json(list(messages)))


def _is_user_prompt_request(message: ModelMessage) -> bool:
    return isinstance(message, ModelRequest) and any(
        isinstance(part, UserPromptPart) for part in message.parts
    )


async def _next_sequence(db: AsyncSession, *, conversation_id: UUID) -> int:
    await db.execute(
        select(Conversation.id)
        .where(
            Conversation.id == conversation_id,
            Conversation.deleted == False,  # noqa: E712
        )
        .with_for_update()
    )
    current = await db.scalar(
        select(func.max(ConversationMessage.sequence)).where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.deleted == False,  # noqa: E712
        )
    )
    return int(current or 0) + 1


def _role_for_message(message: dict[str, Any]) -> str:
    if message.get("kind") == "response":
        return "assistant"

    part_kinds = {
        part.get("part_kind") for part in message.get("parts", []) if isinstance(part, dict)
    }
    if "user-prompt" in part_kinds:
        return "user"
    if "tool-return" in part_kinds or "retry-prompt" in part_kinds:
        return "tool"
    if "system-prompt" in part_kinds:
        return "system"
    return "user"


def _first_tool_name(message: dict[str, Any]) -> str | None:
    for part in message.get("parts", []):
        if isinstance(part, dict) and part.get("tool_name"):
            return str(part["tool_name"])
    return None


def _tool_approval_metadata_for_message(
    message: dict[str, Any],
    tool_approval_metadata_by_call_id: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Mapping[str, Any]]:
    if not tool_approval_metadata_by_call_id:
        return {}

    approval_results: dict[str, Mapping[str, Any]] = {}
    for part in message.get("parts", []):
        if not isinstance(part, dict):
            continue
        tool_call_id = part.get("tool_call_id")
        if not isinstance(tool_call_id, str):
            continue
        approval_metadata = tool_approval_metadata_by_call_id.get(tool_call_id)
        if approval_metadata is not None:
            approval_results[tool_call_id] = approval_metadata

    return approval_results
