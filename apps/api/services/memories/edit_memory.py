# apps/api/services/memories/edit_memory.py

"""Apply a human correction through the existing memory write service."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events.enums import AuditAction
from services.memories.authorisation import (
    ensure_can_edit_memory,
    get_visible_memory,
    resolve_memory_agent,
)
from services.memories.domain import MEMORY_SOURCE_USER, MemoryProvenance
from services.memories.schemas import MemoryResponse, MemoryUpdateRequest
from services.memories.update_memory import update_memory
from services.memories.utils import record_memory_audit


async def edit_memory(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    memory_id: UUID,
    payload: MemoryUpdateRequest,
) -> MemoryResponse:
    """Edit metadata in place or return the superseding content version."""
    memory = await get_visible_memory(
        db,
        workspace=workspace,
        user=actor,
        memory_id=memory_id,
    )
    ensure_can_edit_memory(memory, membership=membership, user=actor)
    agent = await resolve_memory_agent(db, workspace=workspace, memory=memory)
    result = await update_memory(
        db,
        workspace=workspace,
        agent=agent,
        user=actor,
        memory_id=memory.id,
        title=payload.title,
        content_md=payload.content_md,
        importance=payload.importance,
        expires_in_days=payload.expires_in_days,
        provenance=MemoryProvenance(
            source=MEMORY_SOURCE_USER,
            source_conversation_id=None,
            source_run_id=None,
            created_by=MEMORY_SOURCE_USER,
            created_by_user_id=actor.id,
        ),
    )
    await db.flush()
    if result.superseded_memory_id is None:
        await record_memory_audit(
            db,
            workspace_id=workspace.id,
            actor=actor,
            action=AuditAction.UPDATE,
            memory_id=result.memory.id,
            details={
                "event": "user_edited",
                "fields": sorted(payload.model_fields_set),
                "request_id": getattr(request.state, "request_id", None),
            },
        )
    await db.refresh(result.memory)
    return MemoryResponse.from_memory(
        result.memory,
        agent_name=agent.name if result.memory.agent_id else None,
    )
