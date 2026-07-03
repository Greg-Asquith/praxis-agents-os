# apps/api/services/agents/runtime/load_context.py

"""Load database rows needed to execute an agent run."""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError, NotFoundError
from models.agent import Agent
from models.agent_run import AgentRun
from models.conversation import Conversation
from models.skills import Skill
from models.user import User
from models.workspace import Workspace

logger = logging.getLogger(__name__)


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


async def load_agent_skills(db: AsyncSession, agent: Agent) -> list[Skill]:
    """Load active, non-deleted skills assigned to an agent, preserving order."""
    if not agent.skill_ids:
        return []

    skill_ids: list[UUID] = []
    for raw_value in agent.skill_ids:
        try:
            skill_ids.append(UUID(str(raw_value)))
        except ValueError:
            logger.warning(
                "Skipping malformed agent skill id",
                extra={"agent_id": str(agent.id), "skill_id": str(raw_value)},
            )

    if not skill_ids:
        return []

    unique_skill_ids = list(dict.fromkeys(skill_ids))
    rows = (
        await db.scalars(
            select(Skill).where(
                Skill.id.in_(unique_skill_ids),
                Skill.workspace_id == agent.workspace_id,
                Skill.deleted == False,  # noqa: E712
                Skill.is_active.is_(True),
            )
        )
    ).all()
    rows_by_id = {skill.id: skill for skill in rows}
    missing_ids = [skill_id for skill_id in unique_skill_ids if skill_id not in rows_by_id]
    if missing_ids:
        logger.warning(
            "Agent skill ids did not resolve to active skills",
            extra={
                "agent_id": str(agent.id),
                "missing_skill_ids": [str(skill_id) for skill_id in missing_ids],
            },
        )

    return [rows_by_id[skill_id] for skill_id in unique_skill_ids if skill_id in rows_by_id]


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
