# apps/api/services/conversations/utils.py

"""Helpers specific to the conversations service."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError, NotFoundError
from models.agent import Agent
from models.agent_run import AgentRun
from models.conversation import Conversation, ConversationMessage
from models.user import User
from models.workspace import Workspace
from services.agent_runs.domain import TERMINAL_RUN_STATUSES


async def get_conversation_for_actor(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    conversation_id: UUID,
) -> Conversation:
    """Load a conversation visible to the current actor/workspace."""
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.workspace_id == workspace.id,
            Conversation.user_id == actor.id,
            Conversation.deleted == False,  # noqa: E712
        )
    )
    if conversation is None:
        raise NotFoundError(
            "Conversation not found",
            resource_type="conversation",
            resource_id=str(conversation_id),
        )
    return conversation


async def get_assignable_agent_for_workspace(
    db: AsyncSession,
    *,
    workspace: Workspace,
    agent_id: UUID,
) -> Agent:
    """Load an active agent that can be assigned to a new conversation."""
    agent = await db.scalar(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.workspace_id == workspace.id,
            Agent.deleted == False,  # noqa: E712
        )
    )
    if agent is None:
        raise NotFoundError(
            "Agent not found",
            resource_type="agent",
            resource_id=str(agent_id),
        )
    if not agent.is_active:
        raise ConflictError(
            "Agent is not active",
            conflicting_resource="agent",
            details={"agent_id": str(agent.id)},
        )
    return agent


async def get_active_run_for_conversation(
    db: AsyncSession,
    *,
    conversation_id: UUID,
) -> AgentRun | None:
    """Return the newest non-terminal run for a conversation, if any."""
    return await db.scalar(
        select(AgentRun)
        .where(
            AgentRun.conversation_id == conversation_id,
            AgentRun.deleted == False,  # noqa: E712
            AgentRun.status.not_in(TERMINAL_RUN_STATUSES),
        )
        .order_by(AgentRun.created_at.desc())
        .limit(1)
    )


async def get_message_by_client_message_id(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    client_message_id: str,
) -> ConversationMessage | None:
    """Return an existing conversation message for a caller-supplied idempotency key."""
    return await db.scalar(
        select(ConversationMessage).where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.client_message_id == client_message_id,
            ConversationMessage.deleted == False,  # noqa: E712
        )
    )
