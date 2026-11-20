# apps/api/services/memories/list_memories.py

"""List memories visible to one workspace member."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, case, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from models.agent import Agent
from models.agent_memories import AgentMemory
from models.conversation import Conversation
from models.user import User
from models.workspace import Workspace
from services.memories.authorisation import visible_memory_filter, visible_source_conversation
from services.memories.domain import (
    MEMORY_CREATED_BY_USER,
    MEMORY_SCOPE_USER,
    MEMORY_SOURCE_DREAM,
)
from services.memories.schemas import (
    MemoriesListResponse,
    MemoryAudienceCounts,
    MemoryResponse,
    MemorySourceConversation,
)
from utils.pagination import paginate
from utils.search import contains_pattern

MemoryOrigin = Literal["learned", "agent", "person"]
MemoryAudience = Literal["private", "shared"]


def memory_origin_filter(origin: MemoryOrigin) -> ColumnElement[bool]:
    """Matches the page's one origin badge; a person's edit outranks how it began."""
    by_person = or_(
        AgentMemory.created_by == MEMORY_CREATED_BY_USER,
        AgentMemory.last_edited_by_user_at.is_not(None),
    )
    if origin == "person":
        return by_person
    learned = AgentMemory.source == MEMORY_SOURCE_DREAM
    return and_(not_(by_person), learned if origin == "learned" else not_(learned))


async def list_memories(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    audience: MemoryAudience | None,
    memory_type: str | None,
    agent_id: UUID | None,
    status: str,
    q: str | None = None,
    source: MemoryOrigin | None = None,
    limit: int,
    offset: int,
) -> MemoriesListResponse:
    """Return a filtered, workspace-confined memory page with per-audience counts.

    Private is the viewer's own user scope; shared is every scope members can see.
    """
    filters = [
        visible_memory_filter(workspace_id=workspace.id, user_id=actor.id),
        AgentMemory.status == status,
    ]
    if memory_type is not None:
        filters.append(AgentMemory.memory_type == memory_type)
    if source is not None:
        filters.append(memory_origin_filter(source))
    if q and q.strip():
        pattern = contains_pattern(q)
        filters.append(
            or_(
                AgentMemory.title.ilike(pattern, escape="\\"),
                AgentMemory.content_md.ilike(pattern, escape="\\"),
            )
        )
    is_private = AgentMemory.scope == MEMORY_SCOPE_USER
    # Tab counts ignore the tab itself and the Shared tab's agent choice.
    tab = case((is_private, "private"), else_="shared")
    counts = await db.execute(select(tab, func.count()).where(*filters).group_by(tab))
    if audience is not None:
        filters.append(is_private if audience == "private" else not_(is_private))
    if agent_id is not None:
        filters.append(AgentMemory.agent_id == agent_id)

    stmt = (
        select(
            AgentMemory,
            Agent.name,
            Conversation.id.label("source_conversation_id"),
            Conversation.title.label("source_conversation_title"),
        )
        .outerjoin(Agent, Agent.id == AgentMemory.agent_id)
        .outerjoin(
            Conversation,
            visible_source_conversation(workspace=workspace, user_id=actor.id),
        )
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
            MemoryResponse.from_memory(
                memory,
                agent_name=agent_name,
                source_conversation=(
                    MemorySourceConversation(id=conversation_id, title=conversation_title)
                    if conversation_id is not None
                    else None
                ),
                now=now,
            )
            for memory, agent_name, conversation_id, conversation_title in rows
        ],
        audience_counts=MemoryAudienceCounts(**dict(counts.tuples().all())),
        total=total,
        limit=limit,
        offset=offset,
    )
