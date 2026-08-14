# apps/api/services/memories/utils.py

"""Shared memory validation, scope, decay, embedding, and audit helpers."""

import asyncio
import math
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from core.exceptions.general import AppValidationError
from core.settings import settings
from models.agent_memories import AgentMemory
from models.user import User
from services.ai_usage.domain import PURPOSE_EMBEDDING_MEMORY_DEDUP
from services.audit_events.enums import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.embeddings import embed_texts
from services.embeddings.domain import (
    EmbeddingBatch,
    EmbeddingConfigurationError,
    EmbeddingProviderError,
)
from services.memories.domain import (
    ARCHIVE_REASON_USER_DELETED,
    MEMORY_EMBED_JOB_KIND,
    MEMORY_KIND_CORE,
    MEMORY_SCOPE_AGENT,
    MEMORY_SCOPE_USER,
    MEMORY_SCOPE_WORKSPACE,
    MEMORY_STATUS_ACTIVE,
    MEMORY_STATUS_ARCHIVED,
    MEMORY_TYPE_EPISODE,
    MEMORY_TYPE_FACT,
    MEMORY_TYPE_OUTCOME,
    MEMORY_TYPE_PREFERENCE,
    MemoryKind,
    MemoryProvenance,
    MemoryScope,
    MemoryType,
)


def effective_confidence(memory: AgentMemory, *, now: datetime) -> float:
    """Return read-time confidence without mutating the row."""
    if memory.kind == MEMORY_KIND_CORE:
        return float(memory.confidence)
    rates = {
        MEMORY_TYPE_FACT: settings.MEMORY_DECAY_RATE_FACT,
        MEMORY_TYPE_PREFERENCE: settings.MEMORY_DECAY_RATE_PREFERENCE,
        MEMORY_TYPE_EPISODE: settings.MEMORY_DECAY_RATE_EPISODE,
        MEMORY_TYPE_OUTCOME: settings.MEMORY_DECAY_RATE_OUTCOME,
    }
    anchor = memory.last_reinforced_at or memory.created_at
    age_days = max(0.0, (now - anchor).total_seconds() / 86_400)
    decayed = float(memory.confidence) * math.exp(-rates[memory.memory_type] * age_days)
    return max(settings.MEMORY_CONFIDENCE_FLOOR, decayed)


def default_expires_at(memory_type: str, *, now: datetime) -> datetime | None:
    """Resolve the default expiry for a memory type."""
    if memory_type == MEMORY_TYPE_EPISODE:
        return now + timedelta(days=settings.MEMORY_EPISODE_TTL_DAYS)
    if memory_type == MEMORY_TYPE_OUTCOME:
        return now + timedelta(days=settings.MEMORY_OUTCOME_TTL_DAYS)
    return None


def scope_filter(
    scope: str,
    *,
    workspace_id: UUID,
    agent_id: UUID,
    user_id: UUID,
) -> ColumnElement[bool]:
    """Build the only supported exact-scope isolation predicate."""
    base = AgentMemory.workspace_id == workspace_id
    if scope == MEMORY_SCOPE_AGENT:
        return and_(
            base,
            AgentMemory.scope == scope,
            AgentMemory.agent_id == agent_id,
            AgentMemory.user_id.is_(None),
        )
    if scope == MEMORY_SCOPE_USER:
        return and_(
            base,
            AgentMemory.scope == scope,
            AgentMemory.user_id == user_id,
            AgentMemory.agent_id.is_(None),
        )
    if scope == MEMORY_SCOPE_WORKSPACE:
        return and_(
            base,
            AgentMemory.scope == scope,
            AgentMemory.agent_id.is_(None),
            AgentMemory.user_id.is_(None),
        )
    raise AppValidationError("Memory scope is invalid", field="scope")


def visible_scope_filter(
    *,
    workspace_id: UUID,
    agent_id: UUID,
    user_id: UUID,
) -> ColumnElement[bool]:
    """Build the union of the caller's three visible scopes."""
    return or_(
        *(
            scope_filter(
                scope,
                workspace_id=workspace_id,
                agent_id=agent_id,
                user_id=user_id,
            )
            for scope in (
                MEMORY_SCOPE_AGENT,
                MEMORY_SCOPE_USER,
                MEMORY_SCOPE_WORKSPACE,
            )
        )
    )


def active_memory_filter(*, now: datetime | None = None) -> ColumnElement[bool]:
    """Match active memories whose TTL has not elapsed."""
    cutoff = now or datetime.now(UTC)
    return and_(
        AgentMemory.status == MEMORY_STATUS_ACTIVE,
        or_(
            AgentMemory.expires_at.is_(None),
            AgentMemory.expires_at > cutoff,
        ),
    )


def validate_memory_content(*, kind: MemoryKind, title: str, content_md: str) -> None:
    """Validate user/model-authored memory content."""
    if not title.strip():
        raise AppValidationError("Memory title is required", field="title")
    if len(title) > 200:
        raise AppValidationError(
            "Memory title exceeds the character limit",
            field="title",
            details={"max_characters": 200},
        )
    if not content_md.strip():
        raise AppValidationError("Memory content is required", field="content")
    limit = (
        settings.MEMORY_CORE_MAX_CHARS
        if kind == MEMORY_KIND_CORE
        else settings.MEMORY_NOTE_MAX_CHARS
    )
    if len(content_md) > limit:
        raise AppValidationError(
            "Memory content exceeds the character limit",
            field="content",
            details={"max_characters": limit},
        )


def memory_scope_refs(
    scope: MemoryScope, *, agent_id: UUID, user_id: UUID
) -> tuple[UUID | None, UUID | None]:
    """Return agent/user foreign keys for a validated scope."""
    if scope == MEMORY_SCOPE_AGENT:
        return agent_id, None
    if scope == MEMORY_SCOPE_USER:
        return None, user_id
    if scope == MEMORY_SCOPE_WORKSPACE:
        return None, None
    raise AppValidationError("Memory scope is invalid", field="scope")


def memory_text(*, title: str, content_md: str) -> str:
    """Return the stable text embedded for a memory."""
    return f"{title.strip()}\n\n{content_md.strip()}"


async def lock_memory_scope(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    agent_id: UUID,
    user_id: UUID,
    scope: MemoryScope,
    kind: MemoryKind,
) -> None:
    """Serialize writes that share a deduplication and core-cap collection."""
    scope_agent_id, scope_user_id = memory_scope_refs(
        scope,
        agent_id=agent_id,
        user_id=user_id,
    )
    scope_ref = scope_agent_id or scope_user_id or workspace_id
    lock_material = f"{workspace_id}:{scope}:{scope_ref}:{kind}".encode()
    lock_key = int.from_bytes(sha256(lock_material).digest()[:8], "big", signed=True)
    await db.execute(select(func.pg_advisory_xact_lock(lock_key)))


async def repair_memory_lineage_for_purge(
    db: AsyncSession,
    *,
    memory: AgentMemory,
    now: datetime,
) -> int:
    """Keep predecessor rows valid when one version is hard-deleted."""
    predecessors = list(
        await db.scalars(
            select(AgentMemory)
            .where(
                AgentMemory.workspace_id == memory.workspace_id,
                AgentMemory.superseded_by_id == memory.id,
            )
            .with_for_update()
        )
    )
    if memory.superseded_by_id is not None:
        for predecessor in predecessors:
            predecessor.superseded_by_id = memory.superseded_by_id
    else:
        for predecessor in predecessors:
            predecessor.status = MEMORY_STATUS_ARCHIVED
            predecessor.superseded_by_id = None
            predecessor.archived_at = now
            predecessor.archive_reason = ARCHIVE_REASON_USER_DELETED
    return len(predecessors)


async def enqueue_memory_embedding(
    db: AsyncSession,
    *,
    memory: AgentMemory,
    initiated_by_user_id: UUID,
) -> None:
    """Queue one idempotent embedding job for a pending memory row."""
    from services.jobs.enqueue_job import enqueue_job

    await enqueue_job(
        db,
        kind=MEMORY_EMBED_JOB_KIND,
        workspace_id=memory.workspace_id,
        subject_type="memory",
        subject_id=memory.id,
        payload={"memory_id": str(memory.id)},
        initiated_by_user_id=initiated_by_user_id,
    )


async def try_embed_memory(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    title: str,
    content_md: str,
    agent_id: UUID | None = None,
    user_id: UUID | None = None,
) -> EmbeddingBatch | None:
    """Embed a write within the bounded synchronous budget."""
    try:
        return await asyncio.wait_for(
            embed_texts(
                db,
                [memory_text(title=title, content_md=content_md)],
                workspace_id=workspace_id,
                purpose=PURPOSE_EMBEDDING_MEMORY_DEDUP,
                agent_id=agent_id,
                user_id=user_id,
            ),
            timeout=settings.MEMORY_EMBED_WRITE_TIMEOUT_SECONDS,
        )
    except (TimeoutError, EmbeddingConfigurationError, EmbeddingProviderError):
        return None


async def find_near_duplicate(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    agent_id: UUID,
    user_id: UUID,
    scope: MemoryScope,
    kind: MemoryKind,
    vector: list[float],
    embedding_provider: str,
    embedding_model: str,
    embedding_dims: int,
    exclude_id: UUID | None = None,
) -> tuple[AgentMemory | None, float | None]:
    """Return the nearest active same-collection memory and cosine similarity."""
    distance = AgentMemory.embedding.cosine_distance(vector)
    stmt = (
        select(AgentMemory, distance.label("distance"))
        .where(
            scope_filter(
                scope,
                workspace_id=workspace_id,
                agent_id=agent_id,
                user_id=user_id,
            ),
            AgentMemory.kind == kind,
            active_memory_filter(),
            AgentMemory.embedding.is_not(None),
            AgentMemory.embedding_provider == embedding_provider,
            AgentMemory.embedding_model == embedding_model,
            AgentMemory.embedding_dims == embedding_dims,
        )
        .order_by(distance, AgentMemory.id)
        .limit(1)
    )
    if exclude_id is not None:
        stmt = stmt.where(AgentMemory.id != exclude_id)
    row = (await db.execute(stmt)).first()
    if row is None:
        return None, None
    memory, raw_distance = row
    return memory, 1.0 - float(raw_distance)


def build_memory(
    *,
    workspace_id: UUID,
    agent_id: UUID,
    user_id: UUID,
    scope: MemoryScope,
    kind: MemoryKind,
    memory_type: MemoryType,
    title: str,
    content_md: str,
    importance: int,
    expires_at: datetime | None,
    provenance: MemoryProvenance,
    embedding_batch: EmbeddingBatch | None,
) -> AgentMemory:
    """Construct a memory row from validated, server-owned inputs."""
    scope_agent_id, scope_user_id = memory_scope_refs(scope, agent_id=agent_id, user_id=user_id)
    vector = embedding_batch.vectors[0] if embedding_batch is not None else None
    return AgentMemory(
        workspace_id=workspace_id,
        scope=scope,
        agent_id=scope_agent_id,
        user_id=scope_user_id,
        kind=kind,
        memory_type=memory_type,
        title=title.strip(),
        content_md=content_md.strip(),
        embedding=vector,
        embedding_provider=embedding_batch.provider if embedding_batch else None,
        embedding_model=embedding_batch.model if embedding_batch else None,
        embedding_dims=embedding_batch.dimensions if embedding_batch else None,
        importance=importance,
        confidence=settings.MEMORY_DEFAULT_CONFIDENCE,
        expires_at=expires_at,
        source=provenance.source,
        source_conversation_id=provenance.source_conversation_id,
        source_run_id=provenance.source_run_id,
        created_by=provenance.created_by,
        created_by_user_id=provenance.created_by_user_id,
    )


async def record_memory_audit(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    actor: User,
    action: AuditAction,
    memory_id: UUID,
    details: dict[str, object],
) -> None:
    """Record a memory-resource event without risking the primary operation."""
    await record_workspace_audit_event(
        db,
        request=None,
        workspace_id=workspace_id,
        action=action,
        resource_type=AuditResourceType.MEMORY,
        resource_id=memory_id,
        actor=actor,
        details=details,
    )
