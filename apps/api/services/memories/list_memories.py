# apps/api/services/memories/list_memories.py

"""List memories visible to one workspace member."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent
from models.agent_memories import AgentMemory
from models.user import User
from models.workspace import Workspace
from services.memories.authorisation import visible_memory_filter
from services.memories.schemas import MemoriesListResponse, MemoryResponse
from utils.pagination import paginate


async def list_memories(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    scope: str | None,
    kind: str | None,
    memory_type: str | None,
    agent_id: UUID | None,
    status: str,
    limit: int,
    offset: int,
) -> MemoriesListResponse:
    """Return a filtered, workspace-confined memory page."""
    filters = [
        visible_memory_filter(workspace_id=workspace.id, user_id=actor.id),
        AgentMemory.status == status,
    ]
    if scope is not None:
        filters.append(AgentMemory.scope == scope)
    if kind is not None:
        filters.append(AgentMemory.kind == kind)
    if memory_type is not None:
        filters.append(AgentMemory.memory_type == memory_type)
    if agent_id is not None:
        filters.append(AgentMemory.agent_id == agent_id)

    stmt = (
        select(AgentMemory, Agent.name)
        .outerjoin(Agent, Agent.id == AgentMemory.agent_id)
        .where(*filters)
    )
    rows, total = await paginate(
        db,
        stmt,
        AgentMemory.updated_at.desc(),
        AgentMemory.id.desc(),
        limit=limit,
        offset=offset,
        scalars=False,
    )
    now = datetime.now(UTC)
    return MemoriesListResponse(
        memories=[
            MemoryResponse.from_memory(memory, agent_name=agent_name, now=now)
            for memory, agent_name in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
