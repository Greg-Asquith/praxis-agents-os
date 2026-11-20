# apps/api/routes/notifications/archive_notification.py

"""Archive one notification so it leaves the inbox."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.notifications import set_archived_for_workspace
from services.notifications.schemas import NotificationRead

router = APIRouter()


@router.post("/{notification_id}/archive")
async def archive_notification(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    notification_id: Annotated[UUID, Path()],
) -> NotificationRead:
    workspace, _membership = workspace_context
    note = await set_archived_for_workspace(
        db,
        user=actor,
        notification_id=notification_id,
        archived=True,
        active_workspace_id=workspace.id,
    )
    return NotificationRead.model_validate(note)
