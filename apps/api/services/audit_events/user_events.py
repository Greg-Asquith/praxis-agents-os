# apps/api/services/audit_events/user_events.py

"""Shared writer for user-resource audit events."""

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


async def record_user_audit_event(
    db: AsyncSession,
    *,
    action: AuditAction,
    user: User,
    actor: User,
    request: Request,
    details: dict[str, Any],
    status: AuditStatus = AuditStatus.SUCCESS,
    resource_type: AuditResourceType = AuditResourceType.USER,
    workspace_id: UUID | None = None,
) -> None:
    await safe_record_operation_audit_event(
        db,
        workspace_id=workspace_id,
        action=action,
        resource_type=resource_type,
        resource_id=user.id,
        status=status,
        actor_type=AuditActorType.USER,
        actor_id=actor.id,
        actor_display=actor.email,
        requested_by_user_id=actor.id,
        details=details,
        request=request,
    )
