# apps/api/services/memories/save_memory.py

"""Create a memory or explicitly resolve a near duplicate."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from core.settings import settings
from models.agent import Agent
from models.agent_memories import AgentMemory
from models.user import User
from models.workspace import Workspace
from services.memories.domain import (
    MEMORY_KIND_CORE,
    MemoryKind,
    MemoryProvenance,
    MemorySaveResult,
    MemoryScope,
    MemoryType,
)
from services.memories.utils import (
    active_memory_filter,
    build_memory,
    default_expires_at,
    enqueue_memory_embedding,
    find_near_duplicate,
    lock_memory_scope,
    scope_filter,
    try_embed_memory,
    validate_memory_content,
)


async def save_memory(
    db: AsyncSession,
    *,
    workspace: Workspace,
    agent: Agent,
    user: User,
    scope: MemoryScope,
    kind: MemoryKind,
    memory_type: MemoryType,
    title: str,
    content_md: str,
    importance: int = 3,
    expires_in_days: int | None = None,
    provenance: MemoryProvenance,
    duplicate_of: UUID | None = None,
    save_as_new: bool = False,
    _replaces_memory_id: UUID | None = None,
) -> MemorySaveResult:
    """Save a memory, requiring an explicit choice for near duplicates."""
    if duplicate_of is not None and save_as_new:
        raise AppValidationError(
            "duplicate_of and save_as_new cannot be used together",
            field="duplicate_of",
        )
    if importance < 1 or importance > 5:
        raise AppValidationError("Memory importance must be between 1 and 5", field="importance")
    if expires_in_days is not None and expires_in_days <= 0:
        raise AppValidationError("Memory expiry must be greater than zero", field="expires_in_days")
    validate_memory_content(kind=kind, title=title, content_md=content_md)

    embedded = await try_embed_memory(
        db,
        workspace_id=workspace.id,
        title=title,
        content_md=content_md,
    )
    await lock_memory_scope(
        db,
        workspace_id=workspace.id,
        agent_id=agent.id,
        user_id=user.id,
        scope=scope,
        kind=kind,
    )
    nearest = None
    similarity = None
    if embedded is not None:
        nearest, similarity = await find_near_duplicate(
            db,
            workspace_id=workspace.id,
            agent_id=agent.id,
            user_id=user.id,
            scope=scope,
            kind=kind,
            vector=embedded.vectors[0],
            embedding_provider=embedded.provider,
            embedding_model=embedded.model,
            embedding_dims=embedded.dimensions,
            exclude_id=_replaces_memory_id,
        )
        is_near_duplicate = (
            nearest is not None
            and similarity is not None
            and similarity >= settings.MEMORY_DEDUP_SIMILARITY
        )
        if duplicate_of is not None:
            if not is_near_duplicate or nearest.id != duplicate_of:
                raise AppValidationError(
                    "duplicate_of must identify the current nearest in-scope memory",
                    field="duplicate_of",
                )
            nearest.confidence = min(
                1.0,
                float(nearest.confidence) + settings.MEMORY_REINFORCE_CONFIDENCE_STEP,
            )
            nearest.last_reinforced_at = datetime.now(UTC)
            nearest.reinforcement_count += 1
            await db.flush()
            return MemorySaveResult(
                status="reinforced",
                memory=nearest,
                existing_memory=nearest,
                similarity=similarity,
            )
        if is_near_duplicate and not save_as_new:
            return MemorySaveResult(
                status="near_duplicate",
                existing_memory=nearest,
                similarity=similarity,
            )
    elif duplicate_of is not None:
        raise AppValidationError(
            "duplicate_of cannot be verified while embeddings are unavailable",
            field="duplicate_of",
        )

    if kind == MEMORY_KIND_CORE:
        count = await db.scalar(
            select(func.count(AgentMemory.id)).where(
                scope_filter(
                    scope,
                    workspace_id=workspace.id,
                    agent_id=agent.id,
                    user_id=user.id,
                ),
                AgentMemory.kind == MEMORY_KIND_CORE,
                active_memory_filter(),
                AgentMemory.id != _replaces_memory_id if _replaces_memory_id is not None else True,
            )
        )
        if int(count or 0) >= settings.MEMORY_CORE_MAX_PER_SCOPE:
            raise AppValidationError(
                "Core memory limit reached; update or forget an existing core memory first",
                field="kind",
                details={"max_memories": settings.MEMORY_CORE_MAX_PER_SCOPE},
            )

    now = datetime.now(UTC)
    expires_at = (
        now + timedelta(days=expires_in_days)
        if expires_in_days is not None
        else default_expires_at(memory_type, now=now)
    )
    memory = build_memory(
        workspace_id=workspace.id,
        agent_id=agent.id,
        user_id=user.id,
        scope=scope,
        kind=kind,
        memory_type=memory_type,
        title=title,
        content_md=content_md,
        importance=importance,
        expires_at=expires_at,
        provenance=provenance,
        embedding_batch=embedded,
    )
    db.add(memory)
    await db.flush()
    if embedded is None:
        await enqueue_memory_embedding(
            db,
            initiated_by_user_id=user.id,
            memory=memory,
        )
    return MemorySaveResult(status="created", memory=memory)
