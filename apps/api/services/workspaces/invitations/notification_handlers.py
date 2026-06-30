# apps/api/services/workspaces/invitations/notification_handlers.py

"""Notification action handlers owned by workspace invitations."""

from __future__ import annotations

import uuid
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from services.notifications.registry import NotificationActionRegistry, registry
from services.workspaces.invitations import accept_invitation_by_id

if TYPE_CHECKING:
    from models.notification import Notification
    from models.user import User


async def handle_accept_invite(
    db: AsyncSession,
    user: User,
    notification: Notification,
) -> dict[str, Any]:
    """Accept a workspace invitation referenced in a notification payload."""
    payload = notification.payload or {}
    invitation_id = str(payload.get("invitation_id") or "").strip()

    invitation_uuid: uuid.UUID | None = None
    with suppress(ValueError):
        invitation_uuid = uuid.UUID(invitation_id) if invitation_id else None

    if not invitation_id or invitation_uuid is None:
        raise AppValidationError("Notification is missing a valid invitation reference")

    result = await accept_invitation_by_id(db, actor=user, invitation_id=invitation_id)
    return result.model_dump(mode="json")


def register_workspace_invitation_notification_handlers(
    action_registry: NotificationActionRegistry = registry,
) -> None:
    """Register notification handlers owned by workspace invitations."""
    action_registry.register("workspace_invite", "accept_invite", handle_accept_invite)
