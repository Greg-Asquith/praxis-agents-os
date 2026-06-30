# apps/api/services/workspaces/memberships/update_membership.py

"""Update a workspace member's role."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.security import SecurityEventType
from services.workspaces.memberships.utils import get_membership_or_raise
from services.workspaces.schemas import (
    WorkspaceMembershipRead,
    WorkspaceMembershipUpdateRequest,
)
from services.workspaces.utils import (
    MANAGER_ROLES,
    ensure_not_last_owner,
    ensure_team_workspace,
    record_workspace_security_event,
    require_workspace_role,
)


async def update_membership(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace_id: UUID,
    membership_id: UUID,
    payload: WorkspaceMembershipUpdateRequest,
) -> WorkspaceMembershipRead:
    workspace, _ = await require_workspace_role(
        db,
        actor=actor,
        workspace_id=workspace_id,
        allowed_roles=MANAGER_ROLES,
    )
    ensure_team_workspace(workspace)
    membership = await get_membership_or_raise(
        db,
        workspace_id=workspace_id,
        membership_id=membership_id,
    )

    new_role = payload.role.value
    if new_role != membership.role:
        await ensure_not_last_owner(db, membership=membership)
        previous_role = membership.role
        membership.role = new_role
        await db.flush()
        await record_workspace_audit_event(
            db,
            request=request,
            workspace_id=workspace_id,
            action=AuditAction.UPDATE,
            resource_type=AuditResourceType.WORKSPACE_MEMBERSHIP,
            resource_id=membership.id,
            actor=actor,
            details={
                "user_id": str(membership.user_id),
                "previous_role": previous_role,
                "role": new_role,
            },
        )
        await record_workspace_security_event(
            db=db,
            event_type=SecurityEventType.WORKSPACE_MEMBERSHIP_UPDATED,
            request=request,
            actor=actor,
            details={
                "workspace_id": str(workspace_id),
                "membership_id": str(membership.id),
                "user_id": str(membership.user_id),
                "previous_role": previous_role,
                "role": new_role,
            },
        )
        await db.refresh(membership)

    return WorkspaceMembershipRead.from_membership(membership)
