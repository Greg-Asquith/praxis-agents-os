# apps/api/services/conversations/mark_read.py

"""Mark a conversation as read for the current actor."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.workspace import Workspace
from services.agent_runs import reap_abandoned_runs
from services.conversations.schemas import ConversationRead
from services.conversations.utils import (
    get_active_run_for_conversation,
    get_conversation_agent_name,
    get_conversation_for_actor,
)


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
    active_run = await get_active_run_for_conversation(db, conversation_id=conversation.id)
    agent_name = await get_conversation_agent_name(db, conversation=conversation)
    return ConversationRead.from_projection(
        conversation,
        agent_name=agent_name,
        active_run_id=active_run.id if active_run is not None else None,
        active_run_status=active_run.status if active_run is not None else None,
    )
