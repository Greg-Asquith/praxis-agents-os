# apps/api/routes/schedules/get_schedule.py

"""Route for reading a workspace agent schedule."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentWorkspaceDep
from services.agent_schedules import get_schedule as get_schedule_service
from services.agent_schedules.schemas import AgentScheduleRead

router = APIRouter()


@router.get("/{schedule_id}")
async def get_schedule(
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
    schedule_id: Annotated[UUID, Path()],
) -> AgentScheduleRead:
    workspace, _membership = workspace_context
    return await get_schedule_service(db, workspace=workspace, schedule_id=schedule_id)
