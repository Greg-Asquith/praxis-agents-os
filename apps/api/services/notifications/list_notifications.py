# apps/api/services/notifications/list_notifications.py

"""List one person's notifications in the active workspace."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.notification import Notification
from services.notifications.schemas import NotificationRead, NotificationsListResponse
from services.notifications.utils import inbox_conditions
from utils.pagination import paginate


async def list_notifications(
    db: AsyncSession,
    *,
    user_id: UUID,
    workspace_id: UUID,
    unread_only: bool = False,
    limit: int = 20,
    offset: int = 0,
) -> NotificationsListResponse:
    stmt = select(Notification).where(*inbox_conditions(user_id=user_id, workspace_id=workspace_id))
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    items, total = await paginate(
        db,
        stmt,
        Notification.created_at.desc(),
        Notification.id.desc(),
        limit=limit,
        offset=offset,
    )
    return NotificationsListResponse(
        items=[NotificationRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )
