# apps/api/services/conversations/list_conversations.py

"""List conversations visible to the authenticated user in a workspace."""

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.conversation import Conversation
from models.user import User
from models.workspace import Workspace
from services.conversations.schemas import ConversationRead, ConversationsListResponse


async def list_conversations(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    limit: int,
    offset: int,
) -> ConversationsListResponse:
    filters = (
        Conversation.workspace_id == workspace.id,
        Conversation.user_id == actor.id,
        Conversation.deleted == False,  # noqa: E712
    )
    total = await db.scalar(select(func.count()).select_from(Conversation).where(*filters))
    stmt = select(Conversation).where(*filters)
    conversations = (
        await db.scalars(
            stmt.order_by(
                desc(func.coalesce(Conversation.last_message_at, Conversation.created_at)),
                Conversation.created_at.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return ConversationsListResponse(
        conversations=[
            ConversationRead.from_conversation(conversation)
            for conversation in conversations
        ],
        total=total or 0,
        limit=limit,
        offset=offset,
    )
