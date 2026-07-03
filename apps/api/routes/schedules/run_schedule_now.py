# apps/api/routes/schedules/run_schedule_now.py

"""Route for requesting immediate schedule execution."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request, status

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.agent_schedules import run_schedule_now as run_schedule_now_service
from services.agent_schedules.schemas import AgentScheduleRead

router = APIRouter()


@router.post("/{schedule_id}/run-now", status_code=status.HTTP_202_ACCEPTED)
async def run_schedule_now(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    schedule_id: Annotated[UUID, Path()],
) -> AgentScheduleRead:
    workspace, membership = workspace_context
    return await run_schedule_now_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        schedule_id=schedule_id,
    )
