# apps/api/services/notifications/mark_all_read.py

"""Mark every unread notification in one person's inbox read."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from models.notification import Notification
from services.notifications.utils import inbox_conditions


async def mark_all_read(db: AsyncSession, *, user_id: UUID, workspace_id: UUID) -> int:
    """Return the number of notifications marked read."""
    result = await db.execute(
        update(Notification)
        .where(
            *inbox_conditions(user_id=user_id, workspace_id=workspace_id),
            Notification.read_at.is_(None),
        )
        .values(read_at=datetime.now(UTC))
    )
    return getattr(result, "rowcount", 0) or 0
