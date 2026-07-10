# apps/api/services/agent_schedules/create_schedule.py

"""Create a workspace-scoped agent schedule."""

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.agent import AgentSchedule
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.agent_schedules.authorisation import assert_can_create_schedule
from services.agent_schedules.domain import calculate_next_run, normalize_schedule_config
from services.agent_schedules.schemas import (
    AgentScheduleCreateRequest,
    AgentScheduleRead,
    schedule_side_effect_policy,
)
from services.agent_schedules.utils import (
    normalize_default_prompt,
    require_active_agent_for_schedule,
)
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event


async def create_schedule(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    payload: AgentScheduleCreateRequest,
) -> AgentScheduleRead:
    assert_can_create_schedule(membership=membership)
    await require_active_agent_for_schedule(db, workspace=workspace, agent_id=payload.agent_id)

    config = normalize_schedule_config(
        schedule_type=payload.schedule_type,
        cron_expression=payload.cron_expression,
        interval_minutes=payload.interval_minutes,
        run_once_at=payload.run_once_at,
        timezone=payload.timezone,
        supplied_fields={
            "schedule_type",
            "cron_expression",
            "interval_minutes",
            "run_once_at",
            "timezone",
        },
    )
    schedule = AgentSchedule(
        agent_id=payload.agent_id,
        user_id=actor.id,
        workspace_id=workspace.id,
        schedule_type=config.schedule_type,
        cron_expression=config.cron_expression,
        interval_minutes=config.interval_minutes,
        run_once_at=config.run_once_at,
        timezone=config.timezone,
        default_prompt=normalize_default_prompt(payload.default_prompt),
        execution_params=payload.execution_params,
        is_active=payload.is_active,
        next_run_at=calculate_next_run(config) if payload.is_active else None,
    )
    db.add(schedule)
    await db.flush()

    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.CREATE,
        resource_type=AuditResourceType.AGENT_SCHEDULE,
        resource_id=schedule.id,
        actor=actor,
        details={
            "agent_id": str(schedule.agent_id),
            "schedule_type": schedule.schedule_type,
            "timezone": schedule.timezone,
            "is_active": schedule.is_active,
            "side_effect_policy": schedule_side_effect_policy(
                schedule.execution_params,
                default=settings.AGENT_SCHEDULED_SIDE_EFFECT_POLICY,
            ),
        },
    )
    await db.refresh(schedule)
    return AgentScheduleRead.from_schedule(schedule)
