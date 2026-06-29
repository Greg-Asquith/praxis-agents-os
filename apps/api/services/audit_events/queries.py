# apps/api/services/audit_events/queries.py

"""Read access to the audit log for routes to call later."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.audit_event import AuditEvent
from services.audit_events.enums import AuditAction, AuditResourceType, AuditStatus


def _filtered_select(
    base,
    *,
    workspace_id: UUID | str | None,
    resource_type: AuditResourceType | None,
    resource_id: str | None,
    actor_user_id: UUID | str | None,
    action: AuditAction | None,
    status: AuditStatus | None,
    occurred_after: datetime | None,
    occurred_before: datetime | None,
):
    """Apply the shared audit-log filters to a select() statement."""
    if workspace_id is not None:
        base = base.where(AuditEvent.workspace_id == workspace_id)
    if resource_type is not None:
        base = base.where(AuditEvent.resource_type == resource_type)
    if resource_id is not None:
        base = base.where(AuditEvent.resource_id == resource_id)
    if actor_user_id is not None:
        base = base.where(AuditEvent.actor_user_id == actor_user_id)
    if action is not None:
        base = base.where(AuditEvent.action == action)
    if status is not None:
        base = base.where(AuditEvent.status == status)
    if occurred_after is not None:
        base = base.where(AuditEvent.occurred_at >= occurred_after)
    if occurred_before is not None:
        base = base.where(AuditEvent.occurred_at < occurred_before)
    return base


async def list_audit_events(
    db: AsyncSession,
    *,
    workspace_id: UUID | str | None = None,
    resource_type: AuditResourceType | None = None,
    resource_id: str | None = None,
    actor_user_id: UUID | str | None = None,
    action: AuditAction | None = None,
    status: AuditStatus | None = None,
    occurred_after: datetime | None = None,
    occurred_before: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AuditEvent]:
    """Return audit events newest-first, narrowed by the given filters."""
    stmt = _filtered_select(
        select(AuditEvent),
        workspace_id=workspace_id,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_user_id=actor_user_id,
        action=action,
        status=status,
        occurred_after=occurred_after,
        occurred_before=occurred_before,
    )
    stmt = stmt.order_by(AuditEvent.occurred_at.desc()).limit(limit).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def count_audit_events(
    db: AsyncSession,
    *,
    workspace_id: UUID | str | None = None,
    resource_type: AuditResourceType | None = None,
    resource_id: str | None = None,
    actor_user_id: UUID | str | None = None,
    action: AuditAction | None = None,
    status: AuditStatus | None = None,
    occurred_after: datetime | None = None,
    occurred_before: datetime | None = None,
) -> int:
    """Count audit events matching the given filters (for pagination)."""
    stmt = _filtered_select(
        select(func.count(AuditEvent.id)),
        workspace_id=workspace_id,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_user_id=actor_user_id,
        action=action,
        status=status,
        occurred_after=occurred_after,
        occurred_before=occurred_before,
    )
    result = await db.execute(stmt)
    return int(result.scalar_one() or 0)


async def get_audit_event(
    db: AsyncSession,
    *,
    event_id: UUID | str,
    workspace_id: UUID | str | None = None,
) -> AuditEvent | None:
    """Fetch a single audit event by id, optionally scoped to a workspace."""
    stmt = select(AuditEvent).where(AuditEvent.id == event_id)
    if workspace_id is not None:
        stmt = stmt.where(AuditEvent.workspace_id == workspace_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()
