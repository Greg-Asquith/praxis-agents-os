# apps/api/services/agent_schedules/disable_user_schedules.py

"""Turn off every schedule that runs as a user who can no longer act."""

from uuid import UUID

from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import tenant_context
from models.agent import AgentSchedule
from models.user import User
from models.workspace import WorkspaceMembership
from services.audit_events import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    safe_record_operation_audit_event,
)


async def disable_user_schedules(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    user_id: UUID,
    reason: str,
) -> int:
    """Disable the user's active schedules in each workspace they joined, returning the count."""
    # Schedules are under workspace RLS, so switch tenant context per workspace.
    workspace_ids = (
        await db.scalars(
            select(WorkspaceMembership.workspace_id).where(WorkspaceMembership.user_id == user_id)
        )
    ).all()
    disabled = 0
    for workspace_id in workspace_ids:
        async with tenant_context(db, workspace_id=workspace_id, user_id=actor.id):
            schedule_ids = (
                await db.scalars(
                    update(AgentSchedule)
                    .where(
                        AgentSchedule.workspace_id == workspace_id,
                        AgentSchedule.user_id == user_id,
                        AgentSchedule.is_active.is_(True),
                        AgentSchedule.deleted.is_(False),
                    )
                    .values(is_active=False, next_run_at=None)
                    .returning(AgentSchedule.id)
                )
            ).all()
            for schedule_id in schedule_ids:
                await safe_record_operation_audit_event(
                    db,
                    workspace_id=workspace_id,
                    action=AuditAction.DISABLE,
                    resource_type=AuditResourceType.AGENT_SCHEDULE,
                    resource_id=schedule_id,
                    actor_type=AuditActorType.USER,
                    actor_id=actor.id,
                    actor_display=actor.email,
                    requested_by_user_id=actor.id,
                    details={"reason": reason, "schedule_user_id": str(user_id)},
                    request=request,
                )
        disabled += len(schedule_ids)
    return disabled
