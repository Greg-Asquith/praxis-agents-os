# apps/api/services/memories/get_memory_detail.py

"""Read one visible memory and its supersession lineage."""

from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Row, select, union
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from models.agent import Agent
from models.agent_memories import AgentMemory
from models.conversation import Conversation
from models.user import User
from models.workspace import Workspace
from services.memories.authorisation import (
    get_visible_memory,
    visible_memory_filter,
    visible_source_conversation,
)
from services.memories.schemas import (
    MemoryDetailResponse,
    MemoryResponse,
    MemorySourceConversation,
)


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
            select(
                AgentMemory,
                Agent.name,
                Conversation.id.label("source_conversation_id"),
                Conversation.title.label("source_conversation_title"),
            )
            .join(lineage_ids, lineage_ids.c.id == AgentMemory.id)
            .outerjoin(Agent, Agent.id == AgentMemory.agent_id)
            .outerjoin(
                Conversation,
                visible_source_conversation(workspace=workspace, user_id=actor.id),
            )
            .where(visible_memory_filter(workspace_id=workspace.id, user_id=actor.id))
        )
    ).all()
    rows_by_id = {row[0].id: row for row in rows}
    predecessors_by_successor: dict[UUID, list[AgentMemory]] = defaultdict(list)
    for item, *_rest in rows:
        if item.superseded_by_id is not None:
            predecessors_by_successor[item.superseded_by_id].append(item)

    # A merge points several memories at one survivor, so walk every branch.
    seen = {memory.id}
    predecessors: list[AgentMemory] = []
    pending = [memory.id]
    while pending:
        for predecessor in predecessors_by_successor.get(pending.pop(), []):
            if predecessor.id not in seen:
                seen.add(predecessor.id)
                predecessors.append(predecessor)
                pending.append(predecessor.id)
    predecessors.sort(key=lambda item: (item.created_at, item.id))

    successors: list[AgentMemory] = []
    cursor = memory
    while cursor.superseded_by_id is not None:
        successor_row = rows_by_id.get(cursor.superseded_by_id)
        if successor_row is None or successor_row[0].id in seen:
            break
        successor = successor_row[0]
        successors.append(successor)
        seen.add(successor.id)
        cursor = successor

    now = datetime.now(UTC)
    chain = [*predecessors, memory, *successors]
    responses = [_response(rows_by_id[item.id], now=now) for item in chain]
    return MemoryDetailResponse(memory=responses[len(predecessors)], chain=responses)


def _response(row: Row, *, now: datetime) -> MemoryResponse:
    item, agent_name, conversation_id, conversation_title = row
    return MemoryResponse.from_memory(
        item,
        agent_name=agent_name,
        source_conversation=(
            MemorySourceConversation(id=conversation_id, title=conversation_title)
            if conversation_id is not None
            else None
        ),
        now=now,
    )
