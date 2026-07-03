# apps/api/services/agent_schedules/get_schedule.py

"""Read a workspace-scoped agent schedule."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.workspace import Workspace
from services.agent_schedules.runs import get_latest_runs_by_schedule_ids
from services.agent_schedules.schemas import AgentScheduleRead
from services.agent_schedules.utils import get_schedule_for_workspace


async def get_schedule(
    db: AsyncSession,
    *,
    workspace: Workspace,
    schedule_id: UUID,
) -> AgentScheduleRead:
    schedule = await get_schedule_for_workspace(db, workspace=workspace, schedule_id=schedule_id)
    latest_runs = await get_latest_runs_by_schedule_ids(db, [schedule.id])
    return AgentScheduleRead.from_schedule(schedule, latest_run=latest_runs.get(schedule.id))
