# apps/api/services/notifications/utils.py

"""Shared helpers for notification service operations."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.auth import AuthorizationError
from core.exceptions.general import AppValidationError, NotFoundError
from models.notification import Notification
from models.user import User
from services.notifications.registry import registry


def authorize_and_claim_user_notification(
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


def authorize_active_workspace(
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


def validate_actions(notification_type: str, actions: list[dict[str, Any]]) -> None:
    """Reject any advertised action whose key has no registered handler."""
    for action in actions:
        if not isinstance(action, dict):
            raise AppValidationError("Each notification action must be an object", field="actions")
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


async def get_notification_or_raise(
    db: AsyncSession,
    *,
    notification_id: str,
) -> Notification:
    """Fetch a notification or raise the standard not-found exception."""
    note = await db.get(Notification, notification_id)
    if not note or note.deleted:
        raise NotFoundError(
            "Notification not found",
            resource_type="notification",
            resource_id=str(notification_id),
        )
    return note
