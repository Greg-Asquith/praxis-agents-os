# apps/api/services/notifications/service.py

"""Notification service — module-level functions."""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.auth import AuthorizationError
from core.exceptions.general import AppValidationError, NotFoundError
from models.notification import Notification
from models.user import User
from services.audit_events import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    AuditStatus,
    safe_record_operation_audit_event,
)
from services.notifications.registry import registry

logger = logging.getLogger(__name__)


def _authorize_and_claim_user_notification(
    note: Notification,
    *,
    user: User,
    error_message: str,
) -> None:
    """Require ownership, or claim an unassigned notification for the user's email.

    Mutates ``note.recipient_user_id`` when claiming an unassigned notification.
    """

    if note.recipient_user_id == user.id:
        return

    target_email = (note.target_email or "").lower()
    user_email = (getattr(user, "email", None) or "").lower()
    if (
        note.recipient_user_id is None
        and target_email
        and user_email
        and target_email == user_email
    ):
        note.recipient_user_id = user.id
        return

    raise AuthorizationError(error_message)


def _authorize_active_workspace(
    note: Notification,
    *,
    active_workspace_id: str | None,
) -> None:
    """Require notification workspace to match the active workspace, when provided."""
    if (
        note.workspace_id
        and active_workspace_id
        and str(note.workspace_id) != str(active_workspace_id)
    ):
        raise AuthorizationError("Notification does not belong to the active workspace")


def _validate_actions(notification_type: str, actions: list[dict[str, Any]]) -> None:
    """Reject any advertised action whose key has no registered handler."""
    for action in actions:
        if not isinstance(action, dict):
            raise AppValidationError(
                "Each notification action must be an object", field="actions"
            )
        action_key = str(action.get("key") or "").strip()
        if not action_key:
            raise AppValidationError(
                "Each notification action requires a non-empty 'key'", field="actions"
            )
        if registry.get(notification_type, action_key) is None:
            raise AppValidationError(
                "Notification action has no registered handler",
                field="actions",
                details={"notification_type": notification_type, "action_key": action_key},
            )


async def _get_notification_or_raise(
    db: AsyncSession,
    *,
    notification_id: str,
) -> Notification:
    note = await db.get(Notification, notification_id)
    if not note or note.deleted:
        raise NotFoundError(
            "Notification not found",
            resource_type="notification",
            resource_id=str(notification_id),
        )
    return note


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
    _validate_actions(notification_type, actions)
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


async def list_notifications(
    db: AsyncSession,
    *,
    user_id: str,
    status: str | None = "unread",
    notification_type: str | None = None,
    workspace_id: str | None = None,
    include_archived: bool = False,
    limit: int = 50,
) -> list[Notification]:
    stmt = select(Notification).where(
        Notification.recipient_user_id == user_id,
        Notification.deleted.is_(False),
    )
    if not include_archived:
        stmt = stmt.where(Notification.archived.is_(False))
    if status == "unread":
        stmt = stmt.where(Notification.read_at.is_(None))
    elif status == "read":
        stmt = stmt.where(Notification.read_at.is_not(None))
    elif status in ("all", None, ""):
        pass  # no read-state filter
    else:
        raise AppValidationError(
            f"Invalid status filter '{status}'. Must be one of: all, read, unread",
            field="status",
        )
    if notification_type:
        stmt = stmt.where(Notification.notification_type == notification_type)
    if workspace_id:
        stmt = stmt.where(Notification.workspace_id == workspace_id)
    stmt = stmt.order_by(Notification.created_at.desc()).limit(limit)
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def count_unread(
    db: AsyncSession,
    *,
    user_id: str,
    notification_type: str | None = None,
    workspace_id: str | None = None,
) -> int:
    stmt = select(func.count(Notification.id)).where(
        Notification.recipient_user_id == user_id,
        Notification.deleted.is_(False),
        Notification.archived.is_(False),
        Notification.read_at.is_(None),
    )
    if notification_type:
        stmt = stmt.where(Notification.notification_type == notification_type)
    if workspace_id:
        stmt = stmt.where(Notification.workspace_id == workspace_id)
    res = await db.execute(stmt)
    return int(res.scalar_one() or 0)


async def mark_read_for_workspace(
    db: AsyncSession,
    *,
    user: User,
    notification_id: str,
    active_workspace_id: str | None,
) -> Notification:
    note = await _get_notification_or_raise(db, notification_id=notification_id)
    _authorize_active_workspace(note, active_workspace_id=active_workspace_id)
    _authorize_and_claim_user_notification(
        note,
        user=user,
        error_message="Not authorized to update this notification",
    )

    if note.read_at is None:
        note.read_at = datetime.now(UTC)
        await db.flush()
        await safe_record_operation_audit_event(
            db,
            workspace_id=str(note.workspace_id) if note.workspace_id else None,
            action=AuditAction.READ,
            resource_type=AuditResourceType.NOTIFICATION,
            resource_id=str(notification_id),
            status=AuditStatus.SUCCESS,
            actor_type=AuditActorType.USER,
            actor_id=user.id,
            actor_display=user.email,
            requested_by_user_id=user.id,
            details={"notification_id": str(notification_id)},
        )
    return note


async def mark_unread_for_workspace(
    db: AsyncSession,
    *,
    user: User,
    notification_id: str,
    active_workspace_id: str | None,
) -> Notification:
    note = await _get_notification_or_raise(db, notification_id=notification_id)
    _authorize_active_workspace(note, active_workspace_id=active_workspace_id)
    _authorize_and_claim_user_notification(
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


async def set_archived_for_workspace(
    db: AsyncSession,
    *,
    user: User,
    notification_id: str,
    archived: bool,
    active_workspace_id: str | None,
) -> Notification:
    note = await _get_notification_or_raise(db, notification_id=notification_id)
    _authorize_active_workspace(note, active_workspace_id=active_workspace_id)
    _authorize_and_claim_user_notification(
        note,
        user=user,
        error_message="Not authorized to update this notification",
    )
    if note.archived != archived:
        note.archived = archived
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
            details={"notification_id": str(notification_id), "archived": archived},
        )
    return note


async def mark_all_read(
    db: AsyncSession,
    *,
    user_id: str,
    notification_type: str | None = None,
    workspace_id: str | None = None,
) -> int:
    """Bulk-mark all unread notifications as read; returns the number of rows updated."""
    now = datetime.now(UTC)
    stmt = (
        update(Notification)
        .where(
            Notification.recipient_user_id == user_id,
            Notification.deleted.is_(False),
            Notification.archived.is_(False),
            Notification.read_at.is_(None),
        )
        .values(read_at=now)
    )
    if notification_type:
        stmt = stmt.where(Notification.notification_type == notification_type)
    if workspace_id:
        stmt = stmt.where(Notification.workspace_id == workspace_id)
    res = await db.execute(stmt)
    return getattr(res, "rowcount", 0) or 0


async def perform_action_for_workspace(
    db: AsyncSession,
    *,
    user: User,
    notification_id: str,
    action_key: str,
    active_workspace_id: str | None,
) -> dict[str, Any]:
    note = await _get_notification_or_raise(db, notification_id=notification_id)
    _authorize_active_workspace(note, active_workspace_id=active_workspace_id)
    _authorize_and_claim_user_notification(
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

    # Terminal actions consume the notification; non-terminal ones stay actionable
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


async def claim_unassigned_for_email(db: AsyncSession, *, user_id: str, email: str) -> int:
    """Attach any pre-user notifications with matching email to the given user."""
    stmt = (
        update(Notification)
        .where(
            Notification.recipient_user_id.is_(None),
            Notification.target_email == email,
            Notification.deleted.is_(False),
        )
        .values(recipient_user_id=user_id)
    )
    res = await db.execute(stmt)
    return getattr(res, "rowcount", 0) or 0


async def mark_invitation_notifications_actioned(
    db: AsyncSession,
    *,
    user: User,
    invitation_id: str,
) -> int:
    """Mark workspace_invite notifications as actioned/read after email-link acceptance.

    Matches notifications by invitation_id in payload for either the current
    user or the same target_email (pre-claimed). Also claims recipient_user_id
    to the current user.
    """
    stmt = select(Notification).where(
        Notification.notification_type == "workspace_invite",
        Notification.deleted.is_(False),
        Notification.payload["invitation_id"].astext == str(invitation_id),
        or_(
            Notification.recipient_user_id == user.id,
            Notification.target_email == user.email,
        ),
    )
    res = await db.execute(stmt)
    notes = list(res.scalars().all())
    now = datetime.now(UTC)
    count = 0
    for n in notes:
        n.recipient_user_id = n.recipient_user_id or user.id
        n.read_at = n.read_at or now
        n.actioned_at = n.actioned_at or now
        n.action_taken = n.action_taken or "accept_invite"
        n.actions = []
        count += 1
    return count
