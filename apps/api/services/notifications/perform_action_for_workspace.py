# apps/api/services/notifications/perform_action_for_workspace.py

"""Perform a notification action."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.user import User
from services.audit_events import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    AuditStatus,
    safe_record_operation_audit_event,
)
from services.notifications.registry import registry
from services.notifications.utils import (
    authorize_active_workspace,
    authorize_and_claim_user_notification,
    get_notification_or_raise,
)


async def perform_action_for_workspace(
    db: AsyncSession,
    *,
    user: User,
    notification_id: str,
    action_key: str,
    active_workspace_id: str | None,
) -> dict[str, Any]:
    note = await get_notification_or_raise(db, notification_id=notification_id)
    authorize_active_workspace(note, active_workspace_id=active_workspace_id)
    authorize_and_claim_user_notification(
        note,
        user=user,
        error_message="Not authorized to act on this notification",
    )
    if note.actioned_at is not None:
        return {"status": "already_actioned", "action": note.action_taken}

    handler = registry.get(note.notification_type, action_key)
    if not handler:
        raise AppValidationError(
            "Unknown notification action",
            field="action_key",
            details={"notification_type": note.notification_type, "action_key": action_key},
        )

    result = await handler(db=db, user=user, notification=note)

    terminal = registry.is_terminal(note.notification_type, action_key)
    if terminal:
        now = datetime.now(UTC)
        note.actioned_at = now
        note.action_taken = action_key
        note.actions = []
        note.read_at = note.read_at or now

    await db.flush()

    await safe_record_operation_audit_event(
        db,
        workspace_id=str(note.workspace_id) if note.workspace_id else None,
        action=AuditAction.EXECUTE,
        resource_type=AuditResourceType.NOTIFICATION,
        resource_id=str(note.id),
        status=AuditStatus.SUCCESS,
        actor_type=AuditActorType.USER,
        actor_id=user.id,
        actor_display=user.email,
        requested_by_user_id=user.id,
        details={
            "notification_id": str(note.id),
            "action": action_key,
            "type": note.notification_type,
            "terminal": terminal,
        },
    )

    return {"status": "ok", "result": result, "terminal": terminal}
