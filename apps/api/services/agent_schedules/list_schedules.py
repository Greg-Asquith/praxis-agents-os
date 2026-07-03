# apps/api/services/agent_schedules/list_schedules.py

"""List schedules visible in a workspace."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import AgentSchedule
from models.workspace import Workspace
from services.agent_schedules.runs import get_latest_runs_by_schedule_ids
from services.agent_schedules.schemas import AgentScheduleRead, AgentSchedulesListResponse


async def list_schedules(
    db: AsyncSession,
    *,
    workspace: Workspace,
    limit: int,
    offset: int,
    include_inactive: bool,
    agent_id: UUID | None = None,
) -> AgentSchedulesListResponse:
    filters = [
        AgentSchedule.workspace_id == workspace.id,
        AgentSchedule.deleted == False,  # noqa: E712
    ]
    if not include_inactive:
        filters.append(AgentSchedule.is_active.is_(True))
    if agent_id is not None:
        filters.append(AgentSchedule.agent_id == agent_id)

    total = await db.scalar(select(func.count()).select_from(AgentSchedule).where(*filters))
    schedules = (
        await db.scalars(
            select(AgentSchedule)
            .where(*filters)
            .order_by(AgentSchedule.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    latest_runs = await get_latest_runs_by_schedule_ids(
        db,
        [schedule.id for schedule in schedules],
    )

    return AgentSchedulesListResponse(
        items=[
            AgentScheduleRead.from_schedule(
                schedule,
                latest_run=latest_runs.get(schedule.id),
            )
            for schedule in schedules
        ],
        total=total or 0,
        limit=limit,
        offset=offset,
    )
