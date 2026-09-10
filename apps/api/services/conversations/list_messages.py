# apps/api/services/conversations/list_messages.py

"""List persisted messages for a conversation."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.conversation import ConversationMessage
from models.user import User
from models.workspace import Workspace
from services.conversations.schemas import ConversationMessageRead, ConversationMessagesResponse
from services.conversations.shared_projection import (
    load_completed_tool_calls,
    project_shared_message,
)
from services.conversations.utils import get_conversation_for_read


async def list_conversation_messages(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    conversation_id: UUID,
    limit: int = 500,
    before_sequence: int | None = None,
) -> ConversationMessagesResponse:
    """Return a latest-first page of persisted transcript messages ordered by sequence."""
    conversation, _membership = await get_conversation_for_read(
        db,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation_id,
    )
    base_filters = (
        ConversationMessage.conversation_id == conversation.id,
        ConversationMessage.deleted == False,  # noqa: E712
    )
    page_filters = base_filters
    if before_sequence is not None:
        page_filters = (*page_filters, ConversationMessage.sequence < before_sequence)

    total = await db.scalar(
        select(func.count()).select_from(ConversationMessage).where(*base_filters)
    )
    page_ids = (
        select(ConversationMessage.id)
        .where(*page_filters)
        .order_by(ConversationMessage.sequence.desc())
        .limit(limit)
        .subquery()
    )
    messages = (
        await db.scalars(
            select(ConversationMessage)
            .join(page_ids, ConversationMessage.id == page_ids.c.id)
            .order_by(ConversationMessage.sequence)
        )
    ).all()
    has_more = False
    if messages:
        has_more = (
            await db.scalar(
                select(ConversationMessage.id)
                .where(
                    *base_filters,
                    ConversationMessage.sequence < messages[0].sequence,
                )
                .limit(1)
            )
        ) is not None

    viewer = conversation.user_id != actor.id
    if viewer:
        completed_calls = await load_completed_tool_calls(
            db, conversation=conversation, messages=messages
        )
        message_reads = [
            project_shared_message(message, completed_calls=completed_calls) for message in messages
        ]
    else:
        message_reads = [ConversationMessageRead.from_message(message) for message in messages]

    return ConversationMessagesResponse(
        access="viewer" if viewer else "owner",
        messages=message_reads,
        total=total or 0,
        has_more=has_more,
    )
