# apps/api/services/conversations/get_conversation.py

"""Read one conversation visible to the authenticated user in a workspace."""

from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent
from models.user import User
from models.workspace import Workspace
from services.conversations.schemas import ConversationRead
from services.conversations.utils import (
    get_active_run_for_conversation,
    get_conversation_for_actor,
)


async def get_conversation(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    conversation_id: UUID,
) -> ConversationRead:
    """Return a single conversation, including deliberate reads of agent-call children."""
    conversation = await get_conversation_for_actor(
        db,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation_id,
    )
    agent_name = None
    if conversation.active_agent_id is not None:
        agent_name = await db.scalar(
            select(Agent.name).where(
                and_(
                    Agent.id == conversation.active_agent_id,
                    Agent.workspace_id == workspace.id,
                )
            )
        )
    active_run = await get_active_run_for_conversation(db, conversation_id=conversation.id)
    return ConversationRead.from_projection(
        conversation,
        agent_name=agent_name,
        active_run_id=active_run.id if active_run is not None else None,
        active_run_status=active_run.status if active_run is not None else None,
    )
