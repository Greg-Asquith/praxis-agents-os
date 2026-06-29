# apps/api/services/workspaces/invitations_service.py

"""
Invitations service
"""

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.auth import AuthorizationError
from core.exceptions.database import DatabaseError
from core.exceptions.general import AppValidationError
from models.user import User
from models.workspace import Workspace, WorkspaceInvitation, WorkspaceMembership
from services.audit_events import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    AuditStatus,
    safe_record_operation_audit_event,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _invitation_error_guard(operation: str):
    """Re-raise domain errors as-is; wrap unexpected exceptions in DatabaseError."""
    try:
        yield
    except (AppValidationError, AuthorizationError):
        raise
    except Exception as exc:
        logger.error("Failed to accept invitation (%s)", operation, exc_info=True)
        raise DatabaseError("Failed to accept invitation", operation=operation) from exc


def _invitation_result(
    workspace: Workspace,
    membership: WorkspaceMembership,
    invitation: WorkspaceInvitation,
    *,
    status: str,
    message: str,
) -> dict[str, Any]:
    return {
        "workspace": {
            "id": str(workspace.id),
            "slug": workspace.slug,
            "name": workspace.name,
        },
        "role": membership.role,
        "invitation_id": str(invitation.id),
        "status": status,
        "message": message,
    }


async def _accept_invitation(
    db: AsyncSession,
    *,
    current_user: User,
    invitation: WorkspaceInvitation,
) -> dict[str, Any]:
    workspace = await db.execute(
        select(Workspace).where(
            Workspace.id == invitation.workspace_id,
            Workspace.deleted.is_(False),
        )
    )
    workspace = workspace.scalar_one_or_none()
    if not workspace:
        raise AppValidationError("Invalid invitation: workspace not found")

    existing = await db.execute(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.user_id == current_user.id,
        )
    )
    membership = existing.scalar_one_or_none()

    # Idempotent success when the user is already an active member (double-click
    # or retry after a prior accept) — independent of expiry/email checks.
    if membership and not membership.deleted:
        if invitation.accepted_at is None:
            invitation.accepted_at = datetime.now(tz=UTC)
            await db.flush()
        already_accepted = invitation.accepted_at is not None
        return _invitation_result(
            workspace,
            membership,
            invitation,
            status="already_accepted" if already_accepted else "already_member",
            message="Invitation already accepted"
            if already_accepted
            else "You are already a member of this team",
        )

    if invitation.expires_at <= datetime.now(tz=UTC):
        raise AppValidationError("Invitation has expired")

    invite_email = (invitation.email or "").strip().lower()
    user_email = (current_user.email or "").strip().lower()
    if not user_email:
        raise AuthorizationError("Your account does not have a verified email")
    if user_email != invite_email:
        raise AuthorizationError("This invitation was sent to a different email address")

    if membership and membership.deleted:
        membership.restore(cascade=False)
        membership.role = invitation.role
    else:
        membership = WorkspaceMembership(
            workspace_id=workspace.id,
            user_id=current_user.id,
            role=invitation.role,
        )
        db.add(membership)

    invitation.accepted_at = datetime.now(tz=UTC)

    # Flush pending membership/invitation changes before writing the audit row.
    await db.flush()

    await safe_record_operation_audit_event(
        db,
        workspace_id=str(workspace.id),
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.INVITATION,
        resource_id=str(invitation.id),
        status=AuditStatus.SUCCESS,
        actor_type=AuditActorType.USER,
        actor_id=current_user.id,
        actor_display=current_user.email,
        requested_by_user_id=current_user.id,
        details={
            "invitation_id": str(invitation.id),
            "email": invitation.email,
            "role": invitation.role,
            "status": "accepted",
        },
    )

    return _invitation_result(
        workspace,
        membership,
        invitation,
        status="accepted",
        message="Invitation accepted",
    )


async def accept_invitation_by_token(
    db: AsyncSession,
    *,
    current_user: User,
    token: str,
) -> dict[str, Any]:
    async with _invitation_error_guard("accept_invitation_by_token"):
        token = (token or "").strip()
        if not token:
            raise AppValidationError("Invalid or expired invitation link")

        token_hash = WorkspaceInvitation.hash_raw_token(token)
        result = await db.execute(
            select(WorkspaceInvitation)
            .where(
                WorkspaceInvitation.token_hash == token_hash,
                WorkspaceInvitation.deleted.is_(False),
            )
            .with_for_update()
        )
        invitation = result.scalar_one_or_none()
        if not invitation:
            raise AppValidationError("Invalid or expired invitation link")

        return await _accept_invitation(db, current_user=current_user, invitation=invitation)


async def accept_invitation_by_id(
    db: AsyncSession,
    *,
    current_user: User,
    invitation_id: str,
) -> dict[str, Any]:
    async with _invitation_error_guard("accept_invitation_by_id"):
        invitation_id = (invitation_id or "").strip()
        if not invitation_id:
            raise AppValidationError("Invalid or expired invitation link")
        try:
            invitation_uuid = uuid.UUID(invitation_id)
        except ValueError as exc:
            raise AppValidationError("Invalid or expired invitation link") from exc

        result = await db.execute(
            select(WorkspaceInvitation)
            .where(
                WorkspaceInvitation.id == invitation_uuid,
                WorkspaceInvitation.deleted.is_(False),
            )
            .with_for_update()
        )
        invitation = result.scalar_one_or_none()
        if not invitation:
            raise AppValidationError("Invalid or expired invitation link")

        return await _accept_invitation(db, current_user=current_user, invitation=invitation)
