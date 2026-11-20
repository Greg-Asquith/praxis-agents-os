# apps/api/routes/notifications/perform_notification_action.py

"""Run one action a notification offers."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.notifications import perform_action_for_workspace
from services.notifications.schemas import NotificationActionResponse

router = APIRouter()


@router.post("/{notification_id}/actions/{action_key}")
async def perform_notification_action(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    notification_id: Annotated[UUID, Path()],
    action_key: Annotated[str, Path(max_length=64)],
) -> NotificationActionResponse:
    workspace, _membership = workspace_context
    outcome = await perform_action_for_workspace(
        db,
        user=actor,
        notification_id=notification_id,
        action_key=action_key,
        active_workspace_id=workspace.id,
    )
    return NotificationActionResponse.model_validate(outcome)
