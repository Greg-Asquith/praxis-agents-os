# apps/api/services/notifications/count_unread.py

"""Count unread notifications."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.notification import Notification


async def count_unread(
    db: AsyncSession,
    *,
    user_id: str,
    notification_type: str | None = None,
    workspace_id: str | None = None,
) -> int:
    stmt = select(func.count(Notification.id)).where(
        Notification.recipient_user_id == user_id,
        Notification.deleted.is_(False),
        Notification.archived.is_(False),
        Notification.read_at.is_(None),
    )
    if notification_type:
        stmt = stmt.where(Notification.notification_type == notification_type)
    if workspace_id:
        stmt = stmt.where(Notification.workspace_id == workspace_id)
    res = await db.execute(stmt)
    return int(res.scalar_one() or 0)
