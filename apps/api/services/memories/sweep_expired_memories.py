# apps/api/services/memories/sweep_expired_memories.py

"""Archive expired active agent memories."""

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_memories import AgentMemory
from services.audit_events.enums import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
)
from services.audit_events.operations import safe_record_operation_audit_event
from services.memories.domain import (
    ARCHIVE_REASON_EXPIRED,
    MEMORY_STATUS_ACTIVE,
    MEMORY_STATUS_ARCHIVED,
)


async def sweep_expired_memories(db: AsyncSession, *, now: datetime) -> None:
    """Archive active memories whose retention period has ended."""
    expired_rows = list(
        await db.scalars(
            select(AgentMemory).where(
                AgentMemory.status == MEMORY_STATUS_ACTIVE,
                AgentMemory.expires_at.is_not(None),
                AgentMemory.expires_at <= now,
            )
        )
    )
    await db.execute(
        update(AgentMemory)
        .where(
            AgentMemory.status == MEMORY_STATUS_ACTIVE,
            AgentMemory.expires_at.is_not(None),
            AgentMemory.expires_at <= now,
        )
        .values(
            status=MEMORY_STATUS_ARCHIVED,
            archived_at=now,
            archive_reason=ARCHIVE_REASON_EXPIRED,
        )
    )
    for memory in expired_rows:
        await safe_record_operation_audit_event(
            db,
            workspace_id=memory.workspace_id,
            action=AuditAction.DELETE,
            resource_type=AuditResourceType.MEMORY,
            resource_id=memory.id,
            actor_type=AuditActorType.SERVICE,
            actor_display="memory.sweep_expired",
            requested_by_user_id=memory.created_by_user_id,
            details={"event": "archived", "reason": ARCHIVE_REASON_EXPIRED},
        )
