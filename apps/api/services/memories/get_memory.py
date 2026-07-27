# apps/api/services/memories/get_memory.py

"""Scope-confined memory lookup."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from models.agent import Agent
from models.agent_memories import AgentMemory
from models.user import User
from models.workspace import Workspace
from services.memories.utils import visible_scope_filter


async def get_memory(
    db: AsyncSession,
    *,
    workspace: Workspace,
    agent: Agent,
    user: User,
    memory_id: UUID,
) -> AgentMemory:
    """Load a visible memory or report an indistinguishable miss."""
    memory = await db.scalar(
        select(AgentMemory).where(
            AgentMemory.id == memory_id,
            visible_scope_filter(
                workspace_id=workspace.id,
                agent_id=agent.id,
                user_id=user.id,
            ),
        )
    )
    if memory is None:
        raise NotFoundError(
            "Memory not found",
            resource_type="memory",
            resource_id=str(memory_id),
        )
    return memory
