# apps/api/services/notifications/list_notifications.py

"""List notifications."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.notification import Notification


async def list_notifications(
    db: AsyncSession,
    *,
    user_id: str,
    status: str | None = "unread",
    notification_type: str | None = None,
    workspace_id: str | None = None,
    include_archived: bool = False,
    limit: int = 50,
) -> list[Notification]:
    stmt = select(Notification).where(
        Notification.recipient_user_id == user_id,
        Notification.deleted.is_(False),
    )
    if not include_archived:
        stmt = stmt.where(Notification.archived.is_(False))
    if status == "unread":
        stmt = stmt.where(Notification.read_at.is_(None))
    elif status == "read":
        stmt = stmt.where(Notification.read_at.is_not(None))
    elif status in ("all", None, ""):
        pass
    else:
        raise AppValidationError(
            f"Invalid status filter '{status}'. Must be one of: all, read, unread",
            field="status",
        )
    if notification_type:
        stmt = stmt.where(Notification.notification_type == notification_type)
    if workspace_id:
        stmt = stmt.where(Notification.workspace_id == workspace_id)
    stmt = stmt.order_by(Notification.created_at.desc()).limit(limit)
    res = await db.execute(stmt)
    return list(res.scalars().all())
