# apps/api/routes/schedules/list_schedule_runs.py

"""Route for listing schedule run history."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query

from core.dependencies import AsyncDbSessionDep, CurrentWorkspaceDep
from services.agent_schedules import list_schedule_runs as list_schedule_runs_service
from services.agent_schedules.schemas import AgentScheduleRunsListResponse

router = APIRouter()


@router.get("/{schedule_id}/runs")
async def list_schedule_runs(
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
    schedule_id: Annotated[UUID, Path()],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: Annotated[str | None, Query()] = None,
) -> AgentScheduleRunsListResponse:
    workspace, _membership = workspace_context
    return await list_schedule_runs_service(
        db,
        workspace=workspace,
        schedule_id=schedule_id,
        limit=limit,
        offset=offset,
        status=status,
    )
