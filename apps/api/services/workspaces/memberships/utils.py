# apps/api/services/workspaces/memberships/utils.py

"""Helpers for workspace membership operations."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.exceptions.general import NotFoundError
from models.workspace import WorkspaceMembership


async def get_membership_or_raise(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    membership_id: UUID,
    include_deleted: bool = False,
) -> WorkspaceMembership:
    stmt = (
        select(WorkspaceMembership)
        .options(selectinload(WorkspaceMembership.user))
        .where(
            WorkspaceMembership.id == membership_id,
            WorkspaceMembership.workspace_id == workspace_id,
        )
    )
    if not include_deleted:
        stmt = stmt.where(WorkspaceMembership.deleted.is_(False))
    result = await db.execute(stmt)
    membership = result.scalar_one_or_none()
    if membership is None:
        raise NotFoundError(
            "Workspace membership not found",
            resource_type="workspace_membership",
            resource_id=str(membership_id),
        )
    return membership
