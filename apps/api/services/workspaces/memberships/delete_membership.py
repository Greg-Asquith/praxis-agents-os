# apps/api/services/workspaces/memberships/delete_membership.py

"""Remove a member from a workspace."""

from uuid import UUID

from fastapi import Request
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.auth import AuthorizationError
from models.user import User
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.security import SecurityEventType
from services.workspaces.memberships.utils import get_membership_or_raise
from services.workspaces.utils import (
    MANAGER_ROLES,
    READ_ROLES,
    ensure_not_last_owner,
    ensure_team_workspace,
    record_workspace_security_event,
    require_workspace_role,
)


async def delete_membership(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace_id: UUID,
    membership_id: UUID,
) -> None:
    workspace, actor_membership = await require_workspace_role(
        db,
        actor=actor,
        workspace_id=workspace_id,
        allowed_roles=READ_ROLES,
    )
    ensure_team_workspace(workspace)
    membership = await get_membership_or_raise(
        db,
        workspace_id=workspace_id,
        membership_id=membership_id,
    )
    # Managers can remove anyone; other members may only remove themselves (leave).
    if membership.user_id != actor.id and actor_membership.role not in MANAGER_ROLES:
        raise AuthorizationError("Requires higher level role")

    await ensure_not_last_owner(db, membership=membership)
    membership.soft_delete(deleted_by=actor.id, cascade=False)
    await db.execute(
        update(User)
        .where(
            User.id == membership.user_id,
            User.default_workspace_id == workspace_id,
        )
        .values(default_workspace_id=None)
    )
    await db.flush()

    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace_id,
        action=AuditAction.DELETE,
        resource_type=AuditResourceType.WORKSPACE_MEMBERSHIP,
        resource_id=membership.id,
        actor=actor,
        details={"user_id": str(membership.user_id), "role": membership.role},
    )
    await record_workspace_security_event(
        db=db,
        event_type=SecurityEventType.WORKSPACE_MEMBERSHIP_DELETED,
        request=request,
        actor=actor,
        details={
            "workspace_id": str(workspace_id),
            "membership_id": str(membership.id),
            "user_id": str(membership.user_id),
            "role": membership.role,
            "self_removed": membership.user_id == actor.id,
        },
    )
