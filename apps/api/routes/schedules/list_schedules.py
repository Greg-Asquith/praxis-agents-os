# apps/api/routes/schedules/list_schedules.py

"""Route for listing workspace agent schedules."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from core.dependencies import AsyncDbSessionDep, CurrentWorkspaceDep
from services.agent_schedules import list_schedules as list_schedules_service
from services.agent_schedules.schemas import AgentSchedulesListResponse

router = APIRouter()


@router.get("/")
async def list_schedules(
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    include_inactive: bool = False,
    agent_id: Annotated[UUID | None, Query()] = None,
) -> AgentSchedulesListResponse:
    workspace, _membership = workspace_context
    return await list_schedules_service(
        db,
        workspace=workspace,
        limit=limit,
        offset=offset,
        include_inactive=include_inactive,
        agent_id=agent_id,
    )
