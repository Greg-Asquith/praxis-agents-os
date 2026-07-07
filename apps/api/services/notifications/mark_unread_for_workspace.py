# apps/api/services/notifications/mark_unread_for_workspace.py

"""Mark a notification unread."""

from sqlalchemy.ext.asyncio import AsyncSession

from models.notification import Notification
from models.user import User
from services.audit_events import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    AuditStatus,
    safe_record_operation_audit_event,
)
from services.notifications.utils import (
    authorize_active_workspace,
    authorize_and_claim_user_notification,
    get_notification_or_raise,
)


async def mark_unread_for_workspace(
    db: AsyncSession,
    *,
    user: User,
    notification_id: str,
    active_workspace_id: str | None,
) -> Notification:
    note = await get_notification_or_raise(db, notification_id=notification_id)
    authorize_active_workspace(note, active_workspace_id=active_workspace_id)
    authorize_and_claim_user_notification(
        note,
        user=user,
        error_message="Not authorized to update this notification",
    )
    note.read_at = None
    await db.flush()
    await safe_record_operation_audit_event(
        db,
        workspace_id=str(note.workspace_id) if note.workspace_id else None,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.NOTIFICATION,
        resource_id=str(notification_id),
        status=AuditStatus.SUCCESS,
        actor_type=AuditActorType.USER,
        actor_id=user.id,
        actor_display=user.email,
        requested_by_user_id=user.id,
        details={"notification_id": str(notification_id), "read_state": "unread"},
    )
    return note
