# apps/api/services/workspaces/invitations/accept_invitation_utils.py

"""Shared invitation-acceptance implementation."""

from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.exceptions.auth import AuthorizationError
from core.exceptions.general import AppValidationError
from models.user import User
from models.workspace import Workspace, WorkspaceInvitation, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.notifications.service import mark_invitation_notifications_actioned
from services.security import SecurityEventType
from services.workspaces.schemas import (
    WorkspaceInvitationAcceptResponse,
    WorkspaceInvitationRead,
    WorkspaceMembershipRead,
    WorkspaceRead,
)
from services.workspaces.utils import record_workspace_security_event


async def record_failed_accept(
    *,
    request: Request | None,
    actor: User,
    reason: str,
    invitation: WorkspaceInvitation | None = None,
) -> None:
    if request is None:
        return
    await record_workspace_security_event(
        event_type=SecurityEventType.WORKSPACE_INVITATION_FAILED,
        request=request,
        actor=actor,
        committed=True,
        details={
            "reason": reason,
            "workspace_id": str(invitation.workspace_id) if invitation else None,
            "invitation_id": str(invitation.id) if invitation else None,
        },
    )


async def accept_invitation(
    db: AsyncSession,
    *,
    actor: User,
    invitation: WorkspaceInvitation,
    request: Request | None,
) -> WorkspaceInvitationAcceptResponse:
    workspace = await db.scalar(
        select(Workspace).where(
            Workspace.id == invitation.workspace_id,
            Workspace.deleted.is_(False),
        )
    )
    if workspace is None:
        raise AppValidationError("Invalid invitation: workspace not found")

    invite_email = (invitation.email or "").strip().lower()
    user_email = (actor.email or "").strip().lower()
    if not user_email:
        raise AuthorizationError("Your account does not have a verified email")
    if user_email != invite_email:
        raise AuthorizationError("This invitation was sent to a different email address")
    existing = await db.execute(
        select(WorkspaceMembership)
        .options(selectinload(WorkspaceMembership.user))
        .where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.user_id == actor.id,
        )
    )
    membership = existing.scalar_one_or_none()
    if membership and not membership.deleted:
        membership.user = actor
        status = "already_accepted" if invitation.accepted_at is not None else "already_member"
        message = (
            "Invitation already accepted"
            if status == "already_accepted"
            else "You are already a member of this workspace"
        )
        invitation.accepted_at = invitation.accepted_at or datetime.now(UTC)
        await db.flush()
    else:
        if invitation.accepted_at is not None:
            raise AppValidationError("Invitation has already been accepted")
        if invitation.expires_at <= datetime.now(UTC):
            raise AppValidationError("Invitation has expired")

        if membership and membership.deleted:
            membership.restore(cascade=False)
            membership.role = invitation.role
            membership.user = actor
        else:
            membership = WorkspaceMembership(
                workspace_id=workspace.id,
                user_id=actor.id,
                role=invitation.role,
            )
            membership.user = actor
            db.add(membership)

        invitation.accepted_at = datetime.now(UTC)
        await db.flush()
        status = "accepted"
        message = "Invitation accepted"

    await mark_invitation_notifications_actioned(
        db,
        user=actor,
        invitation_id=str(invitation.id),
    )
    await record_workspace_audit_event(
        db,
        request=request,
        workspace_id=workspace.id,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.INVITATION,
        resource_id=invitation.id,
        actor=actor,
        details={
            "email": invitation.email,
            "role": invitation.role,
            "status": status,
            "membership_id": str(membership.id),
        },
    )
    if request is not None:
        await record_workspace_security_event(
            db=db,
            event_type=SecurityEventType.WORKSPACE_INVITATION_ACCEPTED,
            request=request,
            actor=actor,
            details={
                "workspace_id": str(workspace.id),
                "invitation_id": str(invitation.id),
                "membership_id": str(membership.id),
                "status": status,
            },
        )

    await db.refresh(workspace)
    await db.refresh(membership)
    await db.refresh(invitation)
    membership.user = actor

    return WorkspaceInvitationAcceptResponse(
        workspace=WorkspaceRead.from_workspace(workspace, current_user_role=membership.role),
        membership=WorkspaceMembershipRead.from_membership(membership),
        invitation=WorkspaceInvitationRead.from_invitation(invitation),
        status=status,
        message=message,
    )
