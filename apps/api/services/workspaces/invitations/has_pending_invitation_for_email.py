# apps/api/services/workspaces/invitations/has_pending_invitation_for_email.py

"""Check whether an email has a usable workspace invitation."""

from datetime import UTC, datetime

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.workspace import WorkspaceInvitation


async def has_pending_invitation_for_email(db: AsyncSession, *, email: str) -> bool:
    """Return whether an unexpired pending invitation exists for the email."""
    return bool(
        await db.scalar(
            select(
                exists().where(
                    WorkspaceInvitation.email == email,
                    WorkspaceInvitation.accepted_at.is_(None),
                    WorkspaceInvitation.expires_at > datetime.now(UTC),
                    WorkspaceInvitation.deleted.is_(False),
                )
            )
        )
    )
