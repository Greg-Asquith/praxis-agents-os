# apps/api/services/conversations/prune_failed.py

"""Prune empty first conversations left behind by failed runs."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_run import AgentRun
from models.conversation import (
    CONVERSATION_SOURCE_DIRECT,
    CONVERSATION_SOURCE_SCHEDULED,
    Conversation,
    ConversationMessage,
)
from services.agent_runs.domain import RUN_STATUS_FAILED

_PRUNABLE_SOURCES = {CONVERSATION_SOURCE_DIRECT, CONVERSATION_SOURCE_SCHEDULED}


async def prune_failed_empty_conversation_for_run(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    run_id: UUID,
    deleted_by_user_id: UUID,
) -> bool:
    """Soft-delete a failed first conversation only when it has no durable content."""
    run = await db.scalar(
        select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.deleted == False,  # noqa: E712
        )
    )
    if run is None:
        return False

    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.deleted == False,  # noqa: E712
        )
    )
    if conversation is None:
        return False

    if run.conversation_id != conversation.id:
        return False
    if run.status != RUN_STATUS_FAILED:
        return False
    if conversation.source not in _PRUNABLE_SOURCES:
        return False

    message_count = await db.scalar(
        select(func.count())
        .select_from(ConversationMessage)
        .where(
            ConversationMessage.conversation_id == conversation.id,
            ConversationMessage.deleted == False,  # noqa: E712
        )
    )
    if message_count:
        return False

    other_run_count = await db.scalar(
        select(func.count())
        .select_from(AgentRun)
        .where(
            AgentRun.conversation_id == conversation.id,
            AgentRun.id != run.id,
            AgentRun.deleted == False,  # noqa: E712
        )
    )
    if other_run_count:
        return False

    conversation.soft_delete(deleted_by=deleted_by_user_id, cascade=False)
    await db.flush()
    return True
