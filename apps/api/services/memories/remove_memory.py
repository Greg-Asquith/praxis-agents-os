# apps/api/services/memories/remove_memory.py

"""Archive or explicitly purge one human-visible memory."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events.enums import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.memories.authorisation import ensure_can_delete_memory, get_visible_memory
from services.memories.domain import (
    ARCHIVE_REASON_USER_DELETED,
    MEMORY_STATUS_ARCHIVED,
    MEMORY_STATUS_SUPERSEDED,
)
from services.memories.utils import repair_memory_lineage_for_purge


async def remove_memory(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    memory_id: UUID,
    purge: bool,
) -> None:
    """Archive by default; hard-delete only after an explicit purge request."""
    memory = await get_visible_memory(
        db,
        workspace=workspace,
        user=actor,
        memory_id=memory_id,
        for_update=True,
    )
    ensure_can_delete_memory(memory, membership=membership, user=actor)
    if memory.status == MEMORY_STATUS_SUPERSEDED and not purge:
        raise ConflictError(
            "Superseded memories cannot be archived; purge the version explicitly",
            conflicting_resource=str(memory.id),
        )
    now = datetime.now(UTC)
    repaired_predecessors = (
        await repair_memory_lineage_for_purge(db, memory=memory, now=now) if purge else 0
    )
    details = {
        "scope": memory.scope,
        "kind": memory.kind,
        "purge": purge,
        "repaired_predecessors": repaired_predecessors,
    }
    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.DELETE,
        resource_type=AuditResourceType.MEMORY,
        resource_id=memory.id,
        actor=actor,
        details=details,
    )
    if purge:
        await db.delete(memory)
        await db.flush()
        return
    memory.status = MEMORY_STATUS_ARCHIVED
    memory.archived_at = now
    memory.archive_reason = ARCHIVE_REASON_USER_DELETED
    await db.flush()
