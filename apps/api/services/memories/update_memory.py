# apps/api/services/memories/update_memory.py

"""Edit memory metadata or create a superseding content version."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, ConflictError
from models.agent import Agent
from models.user import User
from models.workspace import Workspace
from services.audit_events.enums import AuditAction
from services.memories.domain import (
    MEMORY_STATUS_ACTIVE,
    MEMORY_STATUS_SUPERSEDED,
    MemoryProvenance,
    MemoryUpdateResult,
)
from services.memories.get_memory import get_memory
from services.memories.save_memory import save_memory
from services.memories.utils import (
    enqueue_memory_embedding,
    lock_memory_scope,
    record_memory_audit,
    try_embed_memory,
    validate_memory_content,
)


async def update_memory(
    db: AsyncSession,
    *,
    workspace: Workspace,
    agent: Agent,
    user: User,
    memory_id: UUID,
    title: str | None = None,
    content_md: str | None = None,
    importance: int | None = None,
    expires_in_days: int | None = None,
    provenance: MemoryProvenance,
) -> MemoryUpdateResult:
    """Update metadata in place or preserve content changes as a new version."""
    memory = await get_memory(
        db,
        workspace=workspace,
        agent=agent,
        user=user,
        memory_id=memory_id,
    )
    await lock_memory_scope(
        db,
        workspace_id=workspace.id,
        agent_id=agent.id,
        user_id=user.id,
        scope=memory.scope,
        kind=memory.kind,
    )
    await db.refresh(memory)
    if memory.status != MEMORY_STATUS_ACTIVE:
        raise ConflictError(
            "Only active memories can be updated",
            conflicting_resource=str(memory.id),
        )
    if importance is not None and (importance < 1 or importance > 5):
        raise AppValidationError("Memory importance must be between 1 and 5", field="importance")
    if expires_in_days is not None and expires_in_days <= 0:
        raise AppValidationError("Memory expiry must be greater than zero", field="expires_in_days")

    resolved_title = title if title is not None else memory.title
    content_changed = content_md is not None and content_md.strip() != memory.content_md
    if content_changed:
        validate_memory_content(
            kind=memory.kind,
            title=resolved_title,
            content_md=content_md,
        )
        result = await save_memory(
            db,
            workspace=workspace,
            agent=agent,
            user=user,
            scope=memory.scope,
            kind=memory.kind,
            memory_type=memory.memory_type,
            title=resolved_title,
            content_md=content_md,
            importance=importance if importance is not None else memory.importance,
            expires_in_days=expires_in_days,
            provenance=provenance,
            save_as_new=True,
            _replaces_memory_id=memory.id,
        )
        successor = result.memory
        if successor is None:
            raise RuntimeError("Memory supersession did not create a successor")
        if expires_in_days is None:
            successor.expires_at = memory.expires_at
        memory.status = MEMORY_STATUS_SUPERSEDED
        memory.superseded_by_id = successor.id
        await db.flush()
        await record_memory_audit(
            db,
            workspace_id=workspace.id,
            actor=user,
            action=AuditAction.UPDATE,
            memory_id=memory.id,
            details={
                "event": "superseded",
                "superseded_by_id": str(successor.id),
            },
        )
        return MemoryUpdateResult(
            memory=successor,
            superseded_memory_id=memory.id,
        )

    title_changed = title is not None and title.strip() != memory.title
    if title is not None:
        validate_memory_content(
            kind=memory.kind,
            title=title,
            content_md=memory.content_md,
        )
        memory.title = title.strip()
    if title_changed:
        embedded = await try_embed_memory(
            db,
            workspace_id=workspace.id,
            title=memory.title,
            content_md=memory.content_md,
        )
        memory.embedding = embedded.vectors[0] if embedded is not None else None
        memory.embedding_provider = embedded.provider if embedded is not None else None
        memory.embedding_model = embedded.model if embedded is not None else None
        memory.embedding_dims = embedded.dimensions if embedded is not None else None
    if importance is not None:
        memory.importance = importance
    if expires_in_days is not None:
        memory.expires_at = datetime.now(UTC) + timedelta(days=expires_in_days)
    memory.last_reinforced_at = datetime.now(UTC)
    await db.flush()
    if title_changed and memory.embedding is None:
        await enqueue_memory_embedding(
            db,
            memory=memory,
            initiated_by_user_id=user.id,
        )
    return MemoryUpdateResult(memory=memory)
