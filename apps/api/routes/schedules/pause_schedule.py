# apps/api/routes/schedules/pause_schedule.py

"""Route for pausing a workspace agent schedule."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.agent_schedules import pause_schedule as pause_schedule_service
from services.agent_schedules.schemas import AgentScheduleRead

router = APIRouter()


@router.post("/{schedule_id}/pause")
async def pause_schedule(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    schedule_id: Annotated[UUID, Path()],
) -> AgentScheduleRead:
    workspace, membership = workspace_context
    return await pause_schedule_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        schedule_id=schedule_id,
    )
