# apps/api/services/agents/runtime/entity_references/utils.py

"""Conversation authority helpers for entity-reference resolution."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, NotFoundError
from models.agent import Agent
from models.agent_run import AgentRun
from models.conversation import Conversation
from models.workspace import Workspace


async def resolve_conversation_agent(
    db: AsyncSession,
    conversation: Conversation,
    workspace: Workspace,
    run: AgentRun | None,
) -> tuple[AgentRun | None, Agent]:
    """Resolves a live workspace agent after validating the supplied run."""
    if run is not None and (
        run.conversation_id != conversation.id or run.workspace_id != workspace.id or run.deleted
    ):
        raise AppValidationError(
            "Agent run is not available in this conversation",
            field="run_id",
            details={"run_id": str(run.id)},
        )
    if run is None:
        run = await db.scalar(
            select(AgentRun)
            .where(
                AgentRun.conversation_id == conversation.id,
                AgentRun.workspace_id == workspace.id,
                AgentRun.deleted == False,  # noqa: E712
            )
            .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
            .limit(1)
        )
    agent_id = run.agent_id if run is not None else conversation.active_agent_id
    if agent_id is None:
        raise NotFoundError("Conversation agent not found", resource_type="agent")
    agent = await db.scalar(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.workspace_id == workspace.id,
            Agent.deleted == False,  # noqa: E712
        )
    )
    if agent is None:
        raise NotFoundError(
            "Conversation agent not found",
            resource_type="agent",
            resource_id=str(agent_id),
        )
    return run, agent
