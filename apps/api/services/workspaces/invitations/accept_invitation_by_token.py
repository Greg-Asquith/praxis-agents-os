# apps/api/services/workspaces/invitations/accept_invitation_by_token.py

"""Accept a workspace invitation using its raw token."""

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.auth import AuthorizationError
from core.exceptions.general import AppValidationError
from models.user import User
from models.workspace import WorkspaceInvitation
from services.workspaces.invitations.accept_invitation_utils import (
    accept_invitation,
    record_failed_accept,
)
from services.workspaces.schemas import WorkspaceInvitationAcceptResponse


async def accept_invitation_by_token(
    db: AsyncSession,
    *,
    actor: User,
    token: str,
    request: Request | None = None,
) -> WorkspaceInvitationAcceptResponse:
    token = (token or "").strip()
    if not token:
        await record_failed_accept(request=request, actor=actor, reason="missing_token")
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
    if invitation is None:
        await record_failed_accept(request=request, actor=actor, reason="not_found")
        raise AppValidationError("Invalid or expired invitation link")

    try:
        return await accept_invitation(
            db,
            actor=actor,
            invitation=invitation,
            request=request,
        )
    except (AppValidationError, AuthorizationError) as exc:
        await record_failed_accept(
            request=request,
            actor=actor,
            reason=exc.__class__.__name__,
            invitation=invitation,
        )
        raise
