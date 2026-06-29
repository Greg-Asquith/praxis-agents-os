# apps/api/services/notifications/approval_handlers.py

"""Agent approval notification action handlers.

Handles the 'review' action for agent_approval notifications,
which navigates users to the conversation requiring approval.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from services.notifications.registry import NotificationActionRegistry, registry

if TYPE_CHECKING:
    from models.notification import Notification
    from models.user import User


async def handle_review_approval(
    db: AsyncSession,
    user: User,
    notification: Notification,
) -> dict[str, Any]:
    """
    Handle the 'review' action for agent_approval notifications.

    This action is primarily handled by the frontend which uses the payload
    to navigate to the correct conversation. The backend handler simply
    acknowledges the action and returns navigation info.
    """
    payload = notification.payload or {}

    return {
        "status": "navigate",
        "agent_slug": payload.get("agent_slug"),
        "conversation_id": payload.get("conversation_id"),
        "schedule_id": payload.get("schedule_id"),
        "tool_name": payload.get("tool_name"),
        "message": "Navigate to conversation to review and approve the action",
    }


def register_approval_notification_handlers(
    action_registry: NotificationActionRegistry = registry,
) -> None:
    """Register notification handlers owned by this module."""
    action_registry.register(
        "agent_approval", "review", handle_review_approval, terminal=False
    )
