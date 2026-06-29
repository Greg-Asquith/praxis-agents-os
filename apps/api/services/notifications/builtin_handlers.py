# apps/api/services/notifications/builtin_handlers.py

"""Built-in notification action handlers."""

from __future__ import annotations

import uuid
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from services.notifications.registry import NotificationActionRegistry, registry
from services.workspaces.invitations_service import accept_invitation_by_id

if TYPE_CHECKING:
    from models.notification import Notification
    from models.user import User


async def handle_accept_invite(
    db: AsyncSession,
    user: User,
    notification: Notification,
) -> dict[str, Any]:
    """Accept a workspace invitation referenced in the notification payload.

    The invitations service is the single source of truth: it returns an
    idempotent "already a member"/"already accepted" result and raises
    actionable errors (e.g. "Invitation has expired") which propagate here.
    """
    payload = notification.payload or {}
    invitation_id = str(payload.get("invitation_id") or "").strip()

    invitation_uuid: uuid.UUID | None = None
    with suppress(ValueError):
        invitation_uuid = uuid.UUID(invitation_id) if invitation_id else None

    if not invitation_id or invitation_uuid is None:
        raise AppValidationError("Notification is missing a valid invitation reference")

    return await accept_invitation_by_id(db, current_user=user, invitation_id=invitation_id)


def register_builtin_notification_handlers(
    action_registry: NotificationActionRegistry = registry,
) -> None:
    """Register notification handlers owned by this module."""
    action_registry.register("workspace_invite", "accept_invite", handle_accept_invite)
