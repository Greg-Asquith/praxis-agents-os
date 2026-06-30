# apps/api/services/workspaces/invitations/update_invitation.py

"""Update a pending workspace invitation."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.user import User
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.security import SecurityEventType
from services.workspaces.invitations.utils import (
    ensure_invitation_is_pending,
    get_invitation_or_raise,
    normalize_future_expiry,
)
from services.workspaces.schemas import (
    WorkspaceInvitationRead,
    WorkspaceInvitationUpdateRequest,
)
from services.workspaces.utils import (
    MANAGER_ROLES,
    ensure_team_workspace,
    record_workspace_security_event,
    require_workspace_role,
)


async def update_invitation(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace_id: UUID,
    invitation_id: UUID,
    payload: WorkspaceInvitationUpdateRequest,
) -> WorkspaceInvitationRead:
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
    ensure_invitation_is_pending(invitation)
    changed_fields: list[str] = []

    if "role" in payload.model_fields_set:
        if payload.role is None:
            raise AppValidationError("role cannot be null", field="role")
        if payload.role.value != invitation.role:
            invitation.role = payload.role.value
            changed_fields.append("role")

    if "expires_at" in payload.model_fields_set:
        if payload.expires_at is None:
            raise AppValidationError("expires_at cannot be null", field="expires_at")
        expires_at = normalize_future_expiry(payload.expires_at)
        if expires_at != invitation.expires_at:
            invitation.expires_at = expires_at
            changed_fields.append("expires_at")

    if changed_fields:
        await db.flush()
        await record_workspace_audit_event(
            db,
            request=request,
            workspace_id=workspace_id,
            action=AuditAction.UPDATE,
            resource_type=AuditResourceType.INVITATION,
            resource_id=invitation.id,
            actor=actor,
            details={"fields": changed_fields, "email": invitation.email},
        )
        await record_workspace_security_event(
            db=db,
            event_type=SecurityEventType.WORKSPACE_INVITATION_UPDATED,
            request=request,
            actor=actor,
            details={
                "workspace_id": str(workspace_id),
                "invitation_id": str(invitation.id),
                "email": invitation.email,
                "fields": changed_fields,
            },
        )
        await db.refresh(invitation)

    return WorkspaceInvitationRead.from_invitation(invitation)
