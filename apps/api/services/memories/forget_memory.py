# apps/api/services/memories/forget_memory.py

"""Archive a memory without deleting its history."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from models.agent import Agent
from models.user import User
from models.workspace import Workspace
from services.audit_events.enums import AuditAction
from services.memories.domain import (
    ARCHIVE_REASON_FORGOTTEN,
    MEMORY_STATUS_ARCHIVED,
    MEMORY_STATUS_SUPERSEDED,
    MemoryForgetResult,
)
from services.memories.get_memory import get_memory
from services.memories.utils import lock_memory_scope, record_memory_audit


async def forget_memory(
    db: AsyncSession,
    *,
    workspace: Workspace,
    agent: Agent,
    user: User,
    memory_id: UUID,
    reason: str | None = None,
) -> MemoryForgetResult:
    """Idempotently archive a visible memory."""
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
    if memory.status == MEMORY_STATUS_ARCHIVED:
        return MemoryForgetResult(memory=memory, already_archived=True)
    if memory.status == MEMORY_STATUS_SUPERSEDED:
        raise ConflictError(
            "Superseded memories must retain their successor link",
            conflicting_resource=str(memory.id),
        )
    memory.status = MEMORY_STATUS_ARCHIVED
    memory.archived_at = datetime.now(UTC)
    memory.archive_reason = ARCHIVE_REASON_FORGOTTEN
    await db.flush()
    await record_memory_audit(
        db,
        workspace_id=workspace.id,
        actor=user,
        action=AuditAction.DELETE,
        memory_id=memory.id,
        details={"event": "archived", "reason": reason or ARCHIVE_REASON_FORGOTTEN},
    )
    return MemoryForgetResult(memory=memory, already_archived=False)
