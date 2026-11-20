# apps/api/services/notifications/count_unread.py

"""Count one person's unread notifications in the active workspace."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.notification import Notification
from services.notifications.utils import inbox_conditions


async def count_unread(db: AsyncSession, *, user_id: UUID, workspace_id: UUID) -> int:
    count = await db.scalar(
        select(func.count(Notification.id)).where(
            *inbox_conditions(user_id=user_id, workspace_id=workspace_id),
            Notification.read_at.is_(None),
        )
    )
    return int(count or 0)
