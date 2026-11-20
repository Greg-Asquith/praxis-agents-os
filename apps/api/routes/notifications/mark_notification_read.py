# apps/api/routes/notifications/mark_notification_read.py

"""Mark one notification read."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.notifications import mark_read_for_workspace
from services.notifications.schemas import NotificationRead

router = APIRouter()


@router.post("/{notification_id}/read")
async def mark_notification_read(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    notification_id: Annotated[UUID, Path()],
) -> NotificationRead:
    workspace, _membership = workspace_context
    note = await mark_read_for_workspace(
        db,
        user=actor,
        notification_id=notification_id,
        active_workspace_id=workspace.id,
    )
    return NotificationRead.model_validate(note)
