# apps/api/routes/schedules/create_schedule.py

"""Route for creating a workspace agent schedule."""

from fastapi import APIRouter, Request, status

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.agent_schedules import create_schedule as create_schedule_service
from services.agent_schedules.schemas import AgentScheduleCreateRequest, AgentScheduleRead

router = APIRouter()


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_schedule(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    payload: AgentScheduleCreateRequest,
) -> AgentScheduleRead:
    workspace, membership = workspace_context
    return await create_schedule_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=payload,
    )
