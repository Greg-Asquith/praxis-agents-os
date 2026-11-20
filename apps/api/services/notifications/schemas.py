# apps/api/services/notifications/schemas.py

"""Notification inbox API contracts."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from utils.pagination import OffsetPage


class NotificationRead(BaseModel):
    id: UUID
    notification_type: str
    source: str | None
    title: str
    body: str | None
    payload: dict[str, Any]
    actions: list[dict[str, Any]]
    read_at: datetime | None
    actioned_at: datetime | None
    action_taken: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationsListResponse(OffsetPage):
    items: list[NotificationRead]


class UnreadNotificationCount(BaseModel):
    unread: int


class MarkAllNotificationsReadResponse(BaseModel):
    updated: int


class NotificationActionResponse(BaseModel):
    status: str
    result: dict[str, Any] | None = None
    terminal: bool | None = None
    action: str | None = None
