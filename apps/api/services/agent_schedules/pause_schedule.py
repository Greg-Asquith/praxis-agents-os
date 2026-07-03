# apps/api/services/agent_schedules/pause_schedule.py

"""Pause a workspace-scoped agent schedule."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.agent_schedules.authorisation import assert_can_mutate_schedule
from services.agent_schedules.runs import get_latest_runs_by_schedule_ids
from services.agent_schedules.schemas import AgentScheduleRead
from services.agent_schedules.utils import get_schedule_for_workspace
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event


async def pause_schedule(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    schedule_id: UUID,
) -> AgentScheduleRead:
    schedule = await get_schedule_for_workspace(db, workspace=workspace, schedule_id=schedule_id)
    assert_can_mutate_schedule(schedule=schedule, current_user=actor, membership=membership)

    if schedule.is_active:
        schedule.is_active = False
        schedule.next_run_at = None
        await db.flush()
        await record_workspace_audit_event(
            db,
            request=request,
            workspace_id=workspace.id,
            action=AuditAction.DISABLE,
            resource_type=AuditResourceType.AGENT_SCHEDULE,
            resource_id=schedule.id,
            actor=actor,
            details={"agent_id": str(schedule.agent_id), "schedule_type": schedule.schedule_type},
        )
        await db.refresh(schedule)

    latest_runs = await get_latest_runs_by_schedule_ids(db, [schedule.id])
    return AgentScheduleRead.from_schedule(schedule, latest_run=latest_runs.get(schedule.id))
