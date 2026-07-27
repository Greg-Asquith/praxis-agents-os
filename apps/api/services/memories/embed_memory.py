# apps/api/services/memories/embed_memory.py

"""Embed one pending agent-memory row."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.agent_memories import AgentMemory
from services.audit_events.enums import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
)
from services.audit_events.operations import safe_record_operation_audit_event
from services.embeddings import embed_texts
from services.memories.domain import MEMORY_STATUS_ACTIVE
from services.memories.utils import find_near_duplicate, memory_text


async def embed_memory(db: AsyncSession, *, memory_id: UUID) -> None:
    """Embed one pending row and audit unresolved job-time near duplicates."""
    memory = await db.scalar(
        select(AgentMemory).where(AgentMemory.id == memory_id).with_for_update()
    )
    if memory is None or memory.status != MEMORY_STATUS_ACTIVE or memory.embedding is not None:
        return
    embedded = await embed_texts(
        db,
        [memory_text(title=memory.title, content_md=memory.content_md)],
        workspace_id=memory.workspace_id,
    )
    vector = embedded.vectors[0]
    nearest, similarity = await find_near_duplicate(
        db,
        workspace_id=memory.workspace_id,
        agent_id=memory.agent_id or UUID(int=0),
        user_id=memory.user_id or UUID(int=0),
        scope=memory.scope,
        kind=memory.kind,
        vector=vector,
        embedding_provider=embedded.provider,
        embedding_model=embedded.model,
        embedding_dims=embedded.dimensions,
        exclude_id=memory.id,
    )
    memory.embedding = vector
    memory.embedding_provider = embedded.provider
    memory.embedding_model = embedded.model
    memory.embedding_dims = embedded.dimensions
    await db.flush()
    if (
        nearest is not None
        and similarity is not None
        and similarity >= settings.MEMORY_DEDUP_SIMILARITY
    ):
        await safe_record_operation_audit_event(
            db,
            workspace_id=memory.workspace_id,
            action=AuditAction.UPDATE,
            resource_type=AuditResourceType.MEMORY,
            resource_id=memory.id,
            actor_type=AuditActorType.SERVICE,
            actor_display="memory.embed",
            requested_by_user_id=memory.created_by_user_id,
            details={
                "event": "job_time_near_duplicate",
                "existing_memory_id": str(nearest.id),
                "new_memory_id": str(memory.id),
                "similarity": similarity,
            },
        )
