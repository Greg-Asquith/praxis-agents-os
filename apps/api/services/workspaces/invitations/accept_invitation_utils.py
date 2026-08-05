# apps/api/services/workspaces/invitations/accept_invitation_utils.py

"""Shared invitation-acceptance implementation."""

from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.exceptions.auth import AuthorizationError
from core.exceptions.general import AppValidationError
from models.user import User, UserAuth
from models.workspace import Workspace, WorkspaceInvitation, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.audit_events.workspace_events import record_workspace_audit_event
from services.notifications import mark_invitation_notifications_actioned
from services.security import SecurityEventType
from services.workspaces.schemas import (
    WorkspaceInvitationAcceptResponse,
    WorkspaceInvitationRead,
    WorkspaceMembershipRead,
    WorkspaceRead,
)
from services.workspaces.utils import (
    lock_workspace_membership_writes,
    record_workspace_security_event,
)


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


async def get_verified_email_identity(
    db: AsyncSession,
    *,
    actor: User,
    email: str,
) -> UserAuth | None:
    """Return the active identity that proves the actor owns an email address."""
    return await db.scalar(
        select(UserAuth).where(
            UserAuth.user_id == actor.id,
            UserAuth.email == email,
            UserAuth.email_verified.is_(True),
            UserAuth.deleted.is_(False),
        )
    )


async def accept_invitation(
    db: AsyncSession,
    *,
    actor: User,
    invitation: WorkspaceInvitation,
    request: Request | None,
    invitation_token_verified: bool = False,
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
    verified_identity = None
    if not invitation_token_verified:
        verified_identity = await get_verified_email_identity(
            db,
            actor=actor,
            email=invite_email,
        )
        if verified_identity is None:
            raise AuthorizationError("Verify your email before accepting this invitation")
    existing = await db.execute(
        select(WorkspaceMembership)
        .options(selectinload(WorkspaceMembership.user))
        .where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.user_id == actor.id,
        )
        .with_for_update()
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

        # Invitation and membership rows are locked before workspace serialization.
        await lock_workspace_membership_writes(db, workspace_id=workspace.id)

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
            "identity_proof": "invitation_token"
            if invitation_token_verified
            else "verified_identity",
            "verified_identity_id": str(verified_identity.id) if verified_identity else None,
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
                "identity_proof": "invitation_token"
                if invitation_token_verified
                else "verified_identity",
                "verified_identity_id": str(verified_identity.id) if verified_identity else None,
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
