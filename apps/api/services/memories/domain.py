# apps/api/services/memories/domain.py

"""Controlled vocabularies and value objects for agent memory."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from models.agent_memories import AgentMemory

MEMORY_SCOPE_AGENT = "agent"
MEMORY_SCOPE_USER = "user"
MEMORY_SCOPE_WORKSPACE = "workspace"
MEMORY_KIND_CORE = "core"
MEMORY_KIND_NOTE = "note"
MEMORY_TYPE_FACT = "fact"
MEMORY_TYPE_PREFERENCE = "preference"
MEMORY_TYPE_EPISODE = "episode"
MEMORY_TYPE_OUTCOME = "outcome"
MEMORY_STATUS_ACTIVE = "active"
MEMORY_STATUS_SUPERSEDED = "superseded"
MEMORY_STATUS_ARCHIVED = "archived"
ARCHIVE_REASON_EXPIRED = "expired"
ARCHIVE_REASON_FORGOTTEN = "forgotten"
ARCHIVE_REASON_USER_DELETED = "user_deleted"
MEMORY_SOURCE_USER = "user"
MEMORY_EMBED_JOB_KIND = "memory.embed"
MEMORY_TOOL_NAMES = frozenset({"save_memory", "search_memory", "update_memory", "forget_memory"})

type MemoryScope = Literal["agent", "user", "workspace"]
type MemoryKind = Literal["core", "note"]
type MemoryType = Literal["fact", "preference", "episode", "outcome"]
type MemorySource = Literal["interactive", "scheduled", "delegated", "event", "user"]
type MemoryCreatedBy = Literal["agent", "user"]


@dataclass(frozen=True)
class MemoryProvenance:
    """Server-minted origin fields for a memory write."""

    source: MemorySource
    source_conversation_id: UUID | None
    source_run_id: UUID | None
    created_by: MemoryCreatedBy
    created_by_user_id: UUID | None


@dataclass(frozen=True)
class MemorySaveResult:
    """Outcome of a save attempt, including explicit duplicate resolution."""

    status: Literal["created", "reinforced", "near_duplicate"]
    memory: AgentMemory | None = None
    existing_memory: AgentMemory | None = None
    similarity: float | None = None


@dataclass(frozen=True)
class MemorySearchHit:
    """One ranked memory result."""

    memory: AgentMemory
    score: float
    sources: tuple[str, ...]
    effective_confidence: float


@dataclass(frozen=True)
class MemorySearchResult:
    """Hybrid memory-search results and degradation state."""

    query: str
    results: list[MemorySearchHit]
    mode: Literal["hybrid", "lexical_fallback"]


@dataclass(frozen=True)
class MemoryUpdateResult:
    """Outcome of a metadata edit or content supersession."""

    memory: AgentMemory
    superseded_memory_id: UUID | None = None


@dataclass(frozen=True)
class MemoryForgetResult:
    """Outcome of an idempotent archive operation."""

    memory: AgentMemory
    already_archived: bool
