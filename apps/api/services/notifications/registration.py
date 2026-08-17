# apps/api/services/notifications/registration.py

"""Explicit notification action handler registration."""

from services.notifications.approval_handlers import (
    register_approval_notification_handlers,
)
from services.notifications.registry import NotificationActionRegistry, registry


def register_notification_action_handlers(
    action_registry: NotificationActionRegistry = registry,
) -> NotificationActionRegistry:
    """Register all known notification action handlers.

    Registration is intentionally idempotent: repeated calls overwrite the same
    handler keys with the same callables.
    """
    register_approval_notification_handlers(action_registry)
    return action_registry
