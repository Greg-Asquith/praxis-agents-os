# apps/api/routes/notifications/count_unread_notifications.py

"""Count the signed-in person's unread notifications."""

from fastapi import APIRouter

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.notifications import count_unread
from services.notifications.schemas import UnreadNotificationCount

router = APIRouter()


@router.get("/unread-count")
async def count_unread_notifications(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> UnreadNotificationCount:
    workspace, _membership = workspace_context
    unread = await count_unread(db, user_id=actor.id, workspace_id=workspace.id)
    return UnreadNotificationCount(unread=unread)
