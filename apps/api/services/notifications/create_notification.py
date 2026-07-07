# apps/api/services/notifications/create_notification.py

"""Create notifications."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.notification import Notification
from services.audit_events import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    AuditStatus,
    safe_record_operation_audit_event,
)
from services.notifications.utils import validate_actions


async def create_notification(
    db: AsyncSession,
    *,
    notification_type: str,
    title: str,
    body: str | None = None,
    payload: dict[str, Any] | None = None,
    actions: list[dict[str, Any]] | None = None,
    recipient_user_id: str | None = None,
    target_email: str | None = None,
    workspace_id: str | None = None,
    source: str | None = None,
    requested_by_user_id: str | None = None,
) -> Notification:
    if not recipient_user_id and not target_email:
        raise AppValidationError(
            "Notification requires a recipient_user_id or target_email",
            field="recipient_user_id",
        )
    actions = actions or []
    validate_actions(notification_type, actions)
    note = Notification(
        notification_type=notification_type,
        title=title,
        body=body,
        payload=payload or {},
        actions=actions,
        recipient_user_id=recipient_user_id,
        target_email=target_email,
        workspace_id=workspace_id,
        source=source,
    )
    db.add(note)
    await db.flush()
    await safe_record_operation_audit_event(
        db,
        workspace_id=str(workspace_id) if workspace_id else None,
        action=AuditAction.CREATE,
        resource_type=AuditResourceType.NOTIFICATION,
        resource_id=str(note.id),
        status=AuditStatus.SUCCESS,
        actor_type=AuditActorType.SYSTEM,
        actor_id=None,
        actor_display="System",
        requested_by_user_id=str(requested_by_user_id) if requested_by_user_id else None,
        details={
            "type": notification_type,
            "title": title,
            "recipient_user_id": str(recipient_user_id) if recipient_user_id else None,
            "target_email": target_email,
            "source": source,
        },
    )
    return note
