# apps/api/services/agent_schedules/run_schedule_now.py

"""Request immediate execution for a workspace-scoped agent schedule."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.agent_schedules.authorisation import assert_can_mutate_schedule
from services.agent_schedules.runs import get_latest_runs_by_schedule_ids
from services.agent_schedules.schemas import AgentScheduleRead
from services.agent_schedules.utils import get_schedule_for_workspace
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event


async def run_schedule_now(
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

    if not schedule.is_active:
        raise ConflictError(
            "Cannot run a paused schedule",
            conflicting_resource="agent_schedule",
        )

    requested_at = datetime.now(UTC)
    schedule.next_run_at = requested_at
    await db.flush()
    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.EXECUTE,
        resource_type=AuditResourceType.AGENT_SCHEDULE,
        resource_id=schedule.id,
        actor=actor,
        details={"requested_at": requested_at.isoformat()},
    )
    await db.refresh(schedule)

    latest_runs = await get_latest_runs_by_schedule_ids(db, [schedule.id])
    return AgentScheduleRead.from_schedule(schedule, latest_run=latest_runs.get(schedule.id))
