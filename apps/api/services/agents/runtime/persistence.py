# apps/api/services/agents/runtime/persistence.py

"""Round-trip Pydantic AI messages through ConversationMessage rows."""

import json
from collections.abc import Sequence
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
) -> list[ConversationMessage]:
    """Append newly produced Pydantic AI messages to a conversation."""
    serialized = _dump_messages(messages)
    if not serialized:
        return []

    next_sequence = await _next_sequence(db, conversation_id=conversation.id)
    now = datetime.now(UTC)
    rows: list[ConversationMessage] = []
    for index, message in enumerate(serialized):
        row = ConversationMessage(
            conversation_id=conversation.id,
            role=_role_for_message(message),
            parts=message,
            metadata_json={
                "source": PYDANTIC_AI_MESSAGE_SOURCE,
                "agent_run_id": str(run_id),
                "pydantic_kind": message.get("kind"),
            },
            tool_name=_first_tool_name(message),
            sequence=next_sequence + index,
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
