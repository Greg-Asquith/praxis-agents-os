# apps/api/routes/schedules/update_schedule.py

"""Route for updating a workspace agent schedule."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.agent_schedules import update_schedule as update_schedule_service
from services.agent_schedules.schemas import AgentScheduleRead, AgentScheduleUpdateRequest

router = APIRouter()


@router.patch("/{schedule_id}")
async def update_schedule(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    schedule_id: Annotated[UUID, Path()],
    payload: AgentScheduleUpdateRequest,
) -> AgentScheduleRead:
    workspace, membership = workspace_context
    return await update_schedule_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        schedule_id=schedule_id,
        payload=payload,
    )
