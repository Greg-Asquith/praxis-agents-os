# apps/api/services/workspaces/invitations/delete_invitation.py

"""Revoke a workspace invitation."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.security import SecurityEventType
from services.workspaces.invitations.utils import get_invitation_or_raise
from services.workspaces.utils import (
    MANAGER_ROLES,
    ensure_team_workspace,
    record_workspace_security_event,
    require_workspace_role,
)


async def delete_invitation(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace_id: UUID,
    invitation_id: UUID,
) -> None:
    workspace, _ = await require_workspace_role(
        db,
        actor=actor,
        workspace_id=workspace_id,
        allowed_roles=MANAGER_ROLES,
    )
    ensure_team_workspace(workspace)
    invitation = await get_invitation_or_raise(
        db,
        workspace_id=workspace_id,
        invitation_id=invitation_id,
        lock=True,
    )
    invitation.soft_delete(deleted_by=actor.id, cascade=False)
    await db.flush()

    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace_id,
        action=AuditAction.DELETE,
        resource_type=AuditResourceType.INVITATION,
        resource_id=invitation.id,
        actor=actor,
        details={"email": invitation.email, "accepted": invitation.accepted_at is not None},
    )
    await record_workspace_security_event(
        db=db,
        event_type=SecurityEventType.WORKSPACE_INVITATION_DELETED,
        request=request,
        actor=actor,
        details={
            "workspace_id": str(workspace_id),
            "invitation_id": str(invitation.id),
            "email": invitation.email,
        },
    )
