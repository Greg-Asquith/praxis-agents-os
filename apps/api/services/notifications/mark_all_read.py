# apps/api/services/notifications/mark_all_read.py

"""Bulk mark notifications read."""

from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from models.notification import Notification


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
