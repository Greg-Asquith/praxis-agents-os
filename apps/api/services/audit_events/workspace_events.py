# apps/api/services/audit_events/workspace_events.py

from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from services.audit_events.enums import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    AuditStatus,
)
from services.audit_events.operations import safe_record_operation_audit_event


async def record_workspace_audit_event(
    db: AsyncSession,
    *,
    request: Request | None,
    workspace_id: UUID | None,
    action: AuditAction,
    resource_type: AuditResourceType,
    resource_id: UUID | str | None,
    actor: User,
    details: dict[str, Any],
    status: AuditStatus = AuditStatus.SUCCESS,
) -> None:
    await safe_record_operation_audit_event(
        db,
        workspace_id=workspace_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        status=status,
        actor_type=AuditActorType.USER,
        actor_id=actor.id,
        actor_display=actor.email,
        requested_by_user_id=actor.id,
        details=details,
        request=request,
    )
