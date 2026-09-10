# apps/api/services/conversations/mark_read.py

"""Mark a conversation as read for the current actor."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.workspace import Workspace
from services.agent_runs import reap_abandoned_runs
from services.conversations.get_conversation import get_conversation
from services.conversations.schemas import ConversationRead
from services.conversations.utils import get_conversation_for_actor


async def mark_conversation_read(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    conversation_id: UUID,
) -> ConversationRead:
    """Clear the unread flag on a conversation scoped to the current actor/workspace."""
    conversation = await get_conversation_for_actor(
        db,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation_id,
    )
    conversation.unread = False
    await db.flush()
    await db.refresh(conversation)

    await reap_abandoned_runs(db, conversation_id=conversation.id)
    return await get_conversation(
        db, actor=actor, workspace=workspace, conversation_id=conversation.id
    )
