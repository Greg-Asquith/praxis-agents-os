# apps/api/routes/notifications/__init__.py

"""Notification inbox route registry."""

from fastapi import APIRouter, Depends

from core.dependencies import require_read
from routes.notifications.archive_notification import router as archive_notification_router
from routes.notifications.count_unread_notifications import (
    router as count_unread_notifications_router,
)
from routes.notifications.list_notifications import router as list_notifications_router
from routes.notifications.mark_all_notifications_read import (
    router as mark_all_notifications_read_router,
)
from routes.notifications.mark_notification_read import router as mark_notification_read_router
from routes.notifications.mark_notification_unread import (
    router as mark_notification_unread_router,
)
from routes.notifications.perform_notification_action import (
    router as perform_notification_action_router,
)

router = APIRouter(
    prefix="/notifications", tags=["notifications"], dependencies=[Depends(require_read)]
)
router.include_router(list_notifications_router)
router.include_router(count_unread_notifications_router)
router.include_router(mark_all_notifications_read_router)
router.include_router(mark_notification_read_router)
router.include_router(mark_notification_unread_router)
router.include_router(archive_notification_router)
router.include_router(perform_notification_action_router)

__all__ = ["router"]
