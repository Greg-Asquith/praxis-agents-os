# apps/api/services/workspaces/invitations/accept_pending_invitations_for_user.py

"""Accept valid pending workspace invitations for an authenticated user."""

import logging
from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.workspace import WorkspaceInvitation
from services.workspaces.invitations.accept_invitation_utils import accept_invitation

logger = logging.getLogger(__name__)


async def accept_pending_invitations_for_user(
    db: AsyncSession,
    *,
    user: User,
    request: Request | None = None,
) -> int:
    """Accept all currently valid pending invitations addressed to the user."""
    result = await db.execute(
        select(WorkspaceInvitation)
        .where(
            WorkspaceInvitation.email == user.email,
            WorkspaceInvitation.accepted_at.is_(None),
            WorkspaceInvitation.deleted.is_(False),
            WorkspaceInvitation.expires_at > datetime.now(UTC),
        )
        .order_by(WorkspaceInvitation.created_at.asc())
        .with_for_update(skip_locked=True)
    )
    invitations = result.scalars().all()

    accepted_count = 0
    for invitation in invitations:
        try:
            async with db.begin_nested():
                await accept_invitation(
                    db,
                    actor=user,
                    invitation=invitation,
                    request=request,
                )
        except Exception:
            logger.warning(
                "Skipping pending workspace invitation after acceptance failure",
                exc_info=True,
                extra={
                    "invitation_id": str(invitation.id),
                    "user_id": str(user.id),
                    "workspace_id": str(invitation.workspace_id),
                },
            )
            continue
        accepted_count += 1

    return accepted_count
