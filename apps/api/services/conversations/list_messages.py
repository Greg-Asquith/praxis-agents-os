# apps/api/services/conversations/list_messages.py

"""List persisted messages for a conversation."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.conversation import ConversationMessage
from models.user import User
from models.workspace import Workspace
from services.conversations.schemas import ConversationMessageRead, ConversationMessagesResponse
from services.conversations.utils import get_conversation_for_actor


async def list_conversation_messages(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    conversation_id: UUID,
) -> ConversationMessagesResponse:
    """Return the persisted transcript ordered by sequence."""
    conversation = await get_conversation_for_actor(
        db,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation_id,
    )
    messages = (
        await db.scalars(
            select(ConversationMessage)
            .where(
                ConversationMessage.conversation_id == conversation.id,
                ConversationMessage.deleted == False,  # noqa: E712
            )
            .order_by(ConversationMessage.sequence)
        )
    ).all()
    return ConversationMessagesResponse(
        messages=[ConversationMessageRead.from_message(message) for message in messages],
        total=len(messages),
    )
