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
    kind: Literal["core", "note"]
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
    source: Literal["interactive", "scheduled", "delegated", "event", "user"]
    created_by: Literal["agent", "user"]
    created_by_user_id: UUID | None
    expires_at: datetime | None
    superseded_by_id: UUID | None
    archived_at: datetime | None
    archive_reason: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_memory(
        cls,
        memory: AgentMemory,
        *,
        agent_name: str | None = None,
        now: datetime | None = None,
    ) -> "MemoryResponse":
        measured_at = now or datetime.now(UTC)
        return cls(
            id=memory.id,
            scope=memory.scope,
            kind=memory.kind,
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
            created_at=memory.created_at,
            updated_at=memory.updated_at,
        )


class MemoriesListResponse(OffsetPage):
    """Paginated memory-management response."""

    memories: list[MemoryResponse]


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
