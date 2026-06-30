# apps/api/services/workspaces/invitations/create_invitation.py

"""Create an invitation for a workspace."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from models.user import User
from models.workspace import WorkspaceInvitation, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.security import SecurityEventType
from services.workspaces.schemas import (
    WorkspaceInvitationCreateRequest,
    WorkspaceInvitationCreateResponse,
    WorkspaceInvitationRead,
)
from services.workspaces.utils import (
    MANAGER_ROLES,
    ensure_team_workspace,
    record_workspace_security_event,
    require_workspace_role,
)
from utils.validation import validate_email


async def create_invitation(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace_id: UUID,
    payload: WorkspaceInvitationCreateRequest,
) -> WorkspaceInvitationCreateResponse:
    workspace, _ = await require_workspace_role(
        db,
        actor=actor,
        workspace_id=workspace_id,
        allowed_roles=MANAGER_ROLES,
    )
    ensure_team_workspace(workspace)
    validate_email(payload.email)

    existing_member_id = await db.scalar(
        select(WorkspaceMembership.id)
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.deleted.is_(False),
            User.email == payload.email,
            User.deleted.is_(False),
        )
    )
    if existing_member_id is not None:
        raise ConflictError(
            "User is already a member of this workspace",
            conflicting_resource="workspace_membership",
        )

    raw_token = WorkspaceInvitation.generate_token()
    invitation = WorkspaceInvitation(
        workspace_id=workspace_id,
        email=payload.email,
        role=payload.role.value,
        invited_by=actor.id,
        token_hash=WorkspaceInvitation.hash_raw_token(raw_token),
        expires_at=datetime.now(UTC) + timedelta(days=payload.expires_in_days),
    )
    db.add(invitation)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise ConflictError(
            "A pending invitation already exists for this email",
            conflicting_resource="workspace_invitation",
        ) from exc

    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace_id,
        action=AuditAction.CREATE,
        resource_type=AuditResourceType.INVITATION,
        resource_id=invitation.id,
        actor=actor,
        details={
            "email": invitation.email,
            "role": invitation.role,
            "expires_at": invitation.expires_at.isoformat(),
        },
    )
    await record_workspace_security_event(
        db=db,
        event_type=SecurityEventType.WORKSPACE_INVITATION_CREATED,
        request=request,
        actor=actor,
        details={
            "workspace_id": str(workspace_id),
            "invitation_id": str(invitation.id),
            "email": invitation.email,
            "role": invitation.role,
        },
    )
    await db.refresh(invitation)
    return WorkspaceInvitationCreateResponse(
        invitation=WorkspaceInvitationRead.from_invitation(invitation),
        token=raw_token,
    )
