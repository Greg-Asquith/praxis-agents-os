# apps/api/services/memories/schemas.py

"""Public memory-management API contracts."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from models.agent_memories import AgentMemory
from services.memories.utils import effective_confidence
from utils.pagination import OffsetPage


class MemoryResponse(BaseModel):
    """One human-visible memory version."""

    id: UUID
    scope: Literal["agent", "user", "workspace"]
    memory_type: Literal["fact", "preference", "episode", "outcome"]
    status: Literal["active", "superseded", "archived"]
    title: str
    content_md: str
    importance: int
    confidence: float
    effective_confidence: float
    agent_id: UUID | None
    agent_name: str | None
    user_id: UUID | None
    source: Literal["interactive", "scheduled", "delegated", "event", "user", "dream"]
    created_by: Literal["agent", "user", "system"]
    created_by_user_id: UUID | None
    expires_at: datetime | None
    superseded_by_id: UUID | None
    archived_at: datetime | None
    archive_reason: str | None
    recall_disabled_at: datetime | None
    last_edited_by_user_at: datetime | None
    # Set only when the viewer can open the conversation the memory came from.
    source_conversation_id: UUID | None
    source_conversation_title: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_memory(
        cls,
        memory: AgentMemory,
        *,
        agent_name: str | None = None,
        source_conversation: "MemorySourceConversation | None" = None,
        now: datetime | None = None,
    ) -> "MemoryResponse":
        measured_at = now or datetime.now(UTC)
        return cls(
            id=memory.id,
            scope=memory.scope,
            memory_type=memory.memory_type,
            status=memory.status,
            title=memory.title,
            content_md=memory.content_md,
            importance=memory.importance,
            confidence=float(memory.confidence),
            effective_confidence=effective_confidence(memory, now=measured_at),
            agent_id=memory.agent_id,
            agent_name=agent_name,
            user_id=memory.user_id,
            source=memory.source,
            created_by=memory.created_by,
            created_by_user_id=memory.created_by_user_id,
            expires_at=memory.expires_at,
            superseded_by_id=memory.superseded_by_id,
            archived_at=memory.archived_at,
            archive_reason=memory.archive_reason,
            recall_disabled_at=memory.recall_disabled_at,
            last_edited_by_user_at=memory.last_edited_by_user_at,
            source_conversation_id=source_conversation.id if source_conversation else None,
            source_conversation_title=source_conversation.title if source_conversation else None,
            created_at=memory.created_at,
            updated_at=memory.updated_at,
        )


class MemorySourceConversation(BaseModel):
    """The conversation a memory came from, as the viewer may see it."""

    id: UUID
    title: str | None


class MemoryAudienceCounts(BaseModel):
    """Matching memories per audience, for the page's tabs."""

    private: int = 0
    shared: int = 0


class MemoriesListResponse(OffsetPage):
    """Paginated memory-management response."""

    memories: list[MemoryResponse]
    audience_counts: MemoryAudienceCounts


class MemoryDetailResponse(BaseModel):
    """One memory and its oldest-to-newest supersession lineage."""

    memory: MemoryResponse
    chain: list[MemoryResponse]


class MemoryUpdateRequest(BaseModel):
    """Fields a human may correct on an existing memory."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    content_md: str | None = Field(default=None, min_length=1)
    importance: int | None = Field(default=None, ge=1, le=5)
    expires_in_days: int | None = Field(default=None, gt=0)
    # True stops the memory coming up in a turn by itself; it stays searchable.
    recall_disabled: bool | None = None
