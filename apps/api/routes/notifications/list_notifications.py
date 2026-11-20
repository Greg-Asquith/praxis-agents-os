# apps/api/routes/notifications/list_notifications.py

"""List the signed-in person's notifications, newest first."""

from typing import Annotated

from fastapi import APIRouter, Query

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.notifications import list_notifications as list_notifications_service
from services.notifications.schemas import NotificationsListResponse

router = APIRouter()


@router.get("/")
async def list_notifications(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> NotificationsListResponse:
    workspace, _membership = workspace_context
    return await list_notifications_service(
        db,
        user_id=actor.id,
        workspace_id=workspace.id,
        unread_only=unread_only,
        limit=limit,
        offset=offset,
    )
