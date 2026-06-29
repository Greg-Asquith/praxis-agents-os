# apps/api/services/notifications/registry.py

"""
Registry for notification action handlers.
"""

from collections.abc import Callable
from typing import Any

ActionHandler = Callable[..., Any]


class NotificationActionRegistry:
    def __init__(self) -> None:
        self._handlers: dict[tuple[str, str], ActionHandler] = {}
        self._terminal: dict[tuple[str, str], bool] = {}

    def register(
        self,
        notification_type: str,
        action_key: str,
        handler: ActionHandler,
        *,
        terminal: bool = True,
    ) -> None:
        # terminal=False leaves the notification actionable after the action runs
        self._handlers[(notification_type, action_key)] = handler
        self._terminal[(notification_type, action_key)] = terminal

    def get(self, notification_type: str, action_key: str) -> ActionHandler | None:
        return self._handlers.get((notification_type, action_key))

    def is_terminal(self, notification_type: str, action_key: str) -> bool:
        return self._terminal.get((notification_type, action_key), True)


registry = NotificationActionRegistry()
