# apps/api/services/agent_schedules/list_schedule_runs.py

"""List run history for a workspace-scoped agent schedule."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.exceptions.general import AppValidationError
from models.agent import AgentScheduleRun
from models.workspace import Workspace
from services.agent_schedules.domain import ALL_SCHEDULE_RUN_STATUSES
from services.agent_schedules.schemas import (
    AgentScheduleRunRead,
    AgentScheduleRunsListResponse,
)
from services.agent_schedules.utils import get_schedule_for_workspace
from utils.pagination import paginate


async def list_schedule_runs(
    db: AsyncSession,
    *,
    workspace: Workspace,
    schedule_id: UUID,
    limit: int,
    offset: int,
    status: str | None = None,
) -> AgentScheduleRunsListResponse:
    schedule = await get_schedule_for_workspace(db, workspace=workspace, schedule_id=schedule_id)
    filters = [
        AgentScheduleRun.schedule_id == schedule.id,
        AgentScheduleRun.workspace_id == workspace.id,
        AgentScheduleRun.deleted == False,  # noqa: E712
    ]
    if status is not None:
        if status not in ALL_SCHEDULE_RUN_STATUSES:
            raise AppValidationError(
                "Invalid schedule run status",
                field="status",
                details={"valid_statuses": sorted(ALL_SCHEDULE_RUN_STATUSES)},
            )
        filters.append(AgentScheduleRun.status == status)

    runs, total = await paginate(
        db,
        select(AgentScheduleRun).options(selectinload(AgentScheduleRun.agent_run)).where(*filters),
        AgentScheduleRun.scheduled_for.desc(),
        AgentScheduleRun.created_at.desc(),
        limit=limit,
        offset=offset,
    )

    return AgentScheduleRunsListResponse(
        items=[AgentScheduleRunRead.from_run(run) for run in runs],
        total=total or 0,
        limit=limit,
        offset=offset,
    )
