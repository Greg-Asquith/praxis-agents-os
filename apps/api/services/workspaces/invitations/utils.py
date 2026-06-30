# apps/api/services/workspaces/invitations/utils.py

"""Helpers for workspace invitation operations."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, NotFoundError
from models.workspace import WorkspaceInvitation


async def get_invitation_or_raise(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    invitation_id: UUID,
    include_deleted: bool = False,
    lock: bool = False,
) -> WorkspaceInvitation:
    stmt = select(WorkspaceInvitation).where(
        WorkspaceInvitation.id == invitation_id,
        WorkspaceInvitation.workspace_id == workspace_id,
    )
    if not include_deleted:
        stmt = stmt.where(WorkspaceInvitation.deleted.is_(False))
    if lock:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    invitation = result.scalar_one_or_none()
    if invitation is None:
        raise NotFoundError(
            "Workspace invitation not found",
            resource_type="workspace_invitation",
            resource_id=str(invitation_id),
        )
    return invitation


def ensure_invitation_is_pending(invitation: WorkspaceInvitation) -> None:
    if invitation.accepted_at is not None:
        raise AppValidationError("Accepted invitations cannot be changed", field="invitation_id")
    if invitation.deleted:
        raise AppValidationError("Deleted invitations cannot be changed", field="invitation_id")


def normalize_future_expiry(expires_at: datetime) -> datetime:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= datetime.now(UTC):
        raise AppValidationError("expires_at must be in the future", field="expires_at")
    return expires_at
