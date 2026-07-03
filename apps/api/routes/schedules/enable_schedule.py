# apps/api/routes/schedules/enable_schedule.py

"""Route for enabling a workspace agent schedule."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.agent_schedules import enable_schedule as enable_schedule_service
from services.agent_schedules.schemas import AgentScheduleRead

router = APIRouter()


@router.post("/{schedule_id}/enable")
async def enable_schedule(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    schedule_id: Annotated[UUID, Path()],
) -> AgentScheduleRead:
    workspace, membership = workspace_context
    return await enable_schedule_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        schedule_id=schedule_id,
    )
