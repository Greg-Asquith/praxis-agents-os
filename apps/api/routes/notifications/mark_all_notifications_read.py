# apps/api/routes/notifications/mark_all_notifications_read.py

"""Mark every notification in the signed-in person's inbox read."""

from fastapi import APIRouter

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.notifications import mark_all_read
from services.notifications.schemas import MarkAllNotificationsReadResponse

router = APIRouter()


@router.post("/read-all")
async def mark_all_notifications_read(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> MarkAllNotificationsReadResponse:
    workspace, _membership = workspace_context
    updated = await mark_all_read(db, user_id=actor.id, workspace_id=workspace.id)
    return MarkAllNotificationsReadResponse(updated=updated)
