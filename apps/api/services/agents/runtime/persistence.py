# apps/api/services/agents/runtime/persistence.py

"""Round-trip Pydantic AI messages through ConversationMessage rows."""

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.conversation import Conversation, ConversationMessage

PYDANTIC_AI_MESSAGE_SOURCE = "pydantic_ai"


async def load_message_history(
    db: AsyncSession,
    *,
    conversation_id: UUID,
) -> list[ModelMessage]:
    """Load persisted Pydantic AI history for a conversation.

    Pending: this intentionally returns the full stored history. Add trimming or
    summarization before treating long-running conversations as context-safe.
    """
    rows = await db.scalars(
        select(ConversationMessage)
        .where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.deleted == False,  # noqa: E712
        )
        .order_by(ConversationMessage.sequence)
    )
    stored = [
        row.parts
        for row in rows
        if (row.metadata_json or {}).get("source") == PYDANTIC_AI_MESSAGE_SOURCE
    ]
    if not stored:
        return []
    return list(ModelMessagesTypeAdapter.validate_python(stored))


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


def _dump_messages(messages: Sequence[ModelMessage]) -> list[dict[str, Any]]:
    return json.loads(ModelMessagesTypeAdapter.dump_json(list(messages)))


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
