# apps/api/services/conversations/get_conversation.py

"""Read one conversation visible to the authenticated user in a workspace."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_run import AgentRun
from models.user import User
from models.workspace import Workspace
from services.agent_runs.domain import TERMINAL_RUN_STATUSES
from services.conversation_read_contract import ConversationRead, SharedConversationRead
from services.conversations.utils import (
    conversation_capabilities,
    get_conversation_agent_name,
    get_conversation_for_read,
    shared_conversation_read,
)


async def get_conversation(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    conversation_id: UUID,
) -> ConversationRead | SharedConversationRead:
    """Return a single conversation, including deliberate reads of agent-call children."""
    conversation, membership = await get_conversation_for_read(
        db,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation_id,
    )
    agent_name = await get_conversation_agent_name(db, conversation=conversation)
    active_run = (
        await db.execute(
            select(AgentRun.id, AgentRun.status)
            .where(
                AgentRun.conversation_id == conversation.id,
                AgentRun.workspace_id == workspace.id,
                AgentRun.deleted.is_(False),
                AgentRun.status.not_in(TERMINAL_RUN_STATUSES),
            )
            .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
            .limit(1)
        )
    ).first()
    owner_name = await db.scalar(
        select(User.display_name).where(User.id == conversation.user_id, User.deleted.is_(False))
    )
    capabilities = conversation_capabilities(
        conversation, actor=actor, workspace=workspace, membership=membership
    )
    if conversation.user_id != actor.id:
        return shared_conversation_read(
            conversation,
            owner_name=owner_name,
            agent_name=agent_name,
            active_run_status=active_run.status if active_run is not None else None,
            capabilities=capabilities,
        )
    return ConversationRead.from_projection(
        conversation,
        agent_name=agent_name,
        active_run_id=active_run.id if active_run is not None else None,
        active_run_status=active_run.status if active_run is not None else None,
        owner_name=owner_name,
        capabilities=capabilities,
    )
