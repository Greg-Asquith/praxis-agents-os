# apps/api/routes/schedules/delete_schedule.py

"""Route for deleting a workspace agent schedule."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request, status

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.agent_schedules import delete_schedule as delete_schedule_service

router = APIRouter()


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    schedule_id: Annotated[UUID, Path()],
) -> None:
    workspace, membership = workspace_context
    await delete_schedule_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        schedule_id=schedule_id,
    )
