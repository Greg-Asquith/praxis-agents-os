# apps/api/services/agents/runtime/load_context.py

"""Load database rows needed to execute an agent run."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError, NotFoundError
from models.agent import Agent
from models.agent_run import AgentRun
from models.conversation import Conversation
from models.user import User
from models.workspace import Workspace


async def load_run_context(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    run_id: UUID,
    populate_existing: bool = False,
    lock_run: bool = False,
) -> tuple[AgentRun, Conversation, Agent]:
    """Load a run with its conversation and runtime agent."""
    run_stmt = select(AgentRun).where(
        AgentRun.id == run_id,
        AgentRun.deleted == False,  # noqa: E712
    )
    if lock_run:
        run_stmt = run_stmt.with_for_update()
    if populate_existing:
        run_stmt = run_stmt.execution_options(populate_existing=True)
    run = await db.scalar(run_stmt)
    if run is None:
        raise NotFoundError(
            "Agent run not found",
            resource_type="agent_run",
            resource_id=str(run_id),
        )
    if run.conversation_id != conversation_id:
        raise ConflictError(
            "Agent run does not belong to this conversation",
            conflicting_resource="agent_run",
            details={
                "run_id": str(run.id),
                "run_conversation_id": str(run.conversation_id),
                "requested_conversation_id": str(conversation_id),
            },
        )

    conversation_stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.deleted == False,  # noqa: E712
    )
    if populate_existing:
        conversation_stmt = conversation_stmt.execution_options(populate_existing=True)
    conversation = await db.scalar(conversation_stmt)
    if conversation is None:
        raise NotFoundError(
            "Conversation not found",
            resource_type="conversation",
            resource_id=str(conversation_id),
        )

    agent_stmt = select(Agent).where(
        Agent.id == run.agent_id,
        Agent.deleted == False,  # noqa: E712
    )
    if populate_existing:
        agent_stmt = agent_stmt.execution_options(populate_existing=True)
    agent = await db.scalar(agent_stmt)
    if agent is None:
        raise NotFoundError(
            "Agent not found",
            resource_type="agent",
            resource_id=str(run.agent_id),
        )

    return run, conversation, agent


async def load_actor_context(
    db: AsyncSession,
    run: AgentRun,
) -> tuple[User, Workspace]:
    """Load the user and workspace exposed to runtime dependencies."""
    user = await db.get(User, run.user_id)
    if user is None:
        raise NotFoundError(
            "Agent run user not found",
            resource_type="user",
            resource_id=str(run.user_id),
        )

    workspace = await db.get(Workspace, run.workspace_id)
    if workspace is None:
        raise NotFoundError(
            "Agent run workspace not found",
            resource_type="workspace",
            resource_id=str(run.workspace_id),
        )

    return user, workspace
