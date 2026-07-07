# apps/api/services/agent_schedules/list_schedule_runs.py

"""List run history for a workspace-scoped agent schedule."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.agent import AgentScheduleRun
from models.workspace import Workspace
from services.agent_schedules.runs import (
    RUN_STATUS_ACCEPTED,
    RUN_STATUS_AWAITING_APPROVAL,
    RUN_STATUS_CANCELLED,
    RUN_STATUS_CLAIMED,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_PENDING,
    RUN_STATUS_RETRYABLE_FAILED,
    RUN_STATUS_RUNNING,
    RUN_STATUS_TERMINAL_FAILED,
)
from services.agent_schedules.schemas import (
    AgentScheduleRunRead,
    AgentScheduleRunsListResponse,
)
from services.agent_schedules.utils import get_schedule_for_workspace
from utils.pagination import paginate

VALID_SCHEDULE_RUN_STATUSES = frozenset(
    {
        RUN_STATUS_PENDING,
        RUN_STATUS_CLAIMED,
        RUN_STATUS_ACCEPTED,
        RUN_STATUS_RUNNING,
        RUN_STATUS_AWAITING_APPROVAL,
        RUN_STATUS_COMPLETED,
        RUN_STATUS_RETRYABLE_FAILED,
        RUN_STATUS_TERMINAL_FAILED,
        RUN_STATUS_CANCELLED,
    }
)


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
        if status not in VALID_SCHEDULE_RUN_STATUSES:
            raise AppValidationError(
                "Invalid schedule run status",
                field="status",
                details={"valid_statuses": sorted(VALID_SCHEDULE_RUN_STATUSES)},
            )
        filters.append(AgentScheduleRun.status == status)

    runs, total = await paginate(
        db,
        select(AgentScheduleRun).where(*filters),
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
