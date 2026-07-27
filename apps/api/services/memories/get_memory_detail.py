# apps/api/services/memories/get_memory_detail.py

"""Read one visible memory and its supersession lineage."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, union
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from models.agent import Agent
from models.agent_memories import AgentMemory
from models.user import User
from models.workspace import Workspace
from services.memories.authorisation import get_visible_memory, visible_memory_filter
from services.memories.schemas import MemoryDetailResponse, MemoryResponse


async def get_memory_detail(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    memory_id: UUID,
) -> MemoryDetailResponse:
    """Return one memory plus its visible oldest-to-newest version chain."""
    memory = await get_visible_memory(
        db,
        workspace=workspace,
        user=actor,
        memory_id=memory_id,
    )
    predecessor_row = aliased(AgentMemory)
    predecessors = (
        select(AgentMemory.id, AgentMemory.superseded_by_id)
        .where(AgentMemory.id == memory.id)
        .cte("memory_predecessors", recursive=True)
    )
    predecessors = predecessors.union(
        select(predecessor_row.id, predecessor_row.superseded_by_id).join(
            predecessors,
            predecessor_row.superseded_by_id == predecessors.c.id,
        )
    )

    successor_row = aliased(AgentMemory)
    successors = (
        select(AgentMemory.id, AgentMemory.superseded_by_id)
        .where(AgentMemory.id == memory.id)
        .cte("memory_successors", recursive=True)
    )
    successors = successors.union(
        select(successor_row.id, successor_row.superseded_by_id).join(
            successors,
            successor_row.id == successors.c.superseded_by_id,
        )
    )

    lineage_ids = union(
        select(predecessors.c.id),
        select(successors.c.id),
    ).subquery()
    rows = (
        await db.execute(
            select(AgentMemory, Agent.name)
            .join(lineage_ids, lineage_ids.c.id == AgentMemory.id)
            .outerjoin(Agent, Agent.id == AgentMemory.agent_id)
            .where(visible_memory_filter(workspace_id=workspace.id, user_id=actor.id))
        )
    ).all()
    now = datetime.now(UTC)
    rows_by_id = {item.id: (item, agent_name) for item, agent_name in rows}
    predecessors_by_successor = {
        item.superseded_by_id: item
        for item, _agent_name in rows
        if item.superseded_by_id is not None
    }

    predecessors: list[AgentMemory] = []
    cursor = memory
    seen = {memory.id}
    while (predecessor := predecessors_by_successor.get(cursor.id)) is not None:
        if predecessor.id in seen:
            break
        predecessors.append(predecessor)
        seen.add(predecessor.id)
        cursor = predecessor

    successors: list[AgentMemory] = []
    cursor = memory
    while cursor.superseded_by_id is not None:
        successor_row = rows_by_id.get(cursor.superseded_by_id)
        if successor_row is None:
            break
        successor, _agent_name = successor_row
        if successor.id in seen:
            break
        successors.append(successor)
        seen.add(successor.id)
        cursor = successor

    chain = [*reversed(predecessors), memory, *successors]
    responses = [
        MemoryResponse.from_memory(
            item,
            agent_name=rows_by_id[item.id][1],
            now=now,
        )
        for item in chain
    ]
    current_index = len(predecessors)
    return MemoryDetailResponse(memory=responses[current_index], chain=responses)
