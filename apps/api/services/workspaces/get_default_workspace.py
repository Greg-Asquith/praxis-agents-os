# apps/api/services/workspaces/get_default_workspace.py

"""Helpers for resolving a user's default workspace."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.exceptions.general import AppValidationError
from models.user import User
from models.workspace import Workspace, WorkspaceMembership


def select_default_workspace_membership(
    memberships: list[WorkspaceMembership],
    default_workspace_id: UUID | None,
) -> WorkspaceMembership | None:
    """Select the safest default membership from an already-loaded membership list."""
    if not memberships:
        return None

    if default_workspace_id is not None:
        default_membership = next(
            (
                membership
                for membership in memberships
                if membership.workspace_id == default_workspace_id
            ),
            None,
        )
        if default_membership:
            return default_membership

    personal_membership = next(
        (
            membership
            for membership in memberships
            if getattr(membership.workspace, "is_personal", False)
        ),
        None,
    )
    if personal_membership:
        return personal_membership

    return memberships[0]


async def get_default_workspace_membership_for_user(
    db: AsyncSession,
    user: User,
) -> WorkspaceMembership | None:
    """Get the user's default active workspace membership.

    Selection order is the user's configured default workspace, then their
    personal workspace, then their oldest active workspace membership.
    """
    result = await db.execute(
        select(WorkspaceMembership)
        .join(Workspace, Workspace.id == WorkspaceMembership.workspace_id)
        .options(selectinload(WorkspaceMembership.workspace))
        .where(
            WorkspaceMembership.user_id == user.id,
            WorkspaceMembership.deleted.is_(False),
            Workspace.deleted.is_(False),
        )
        .order_by(WorkspaceMembership.created_at)
    )
    memberships = list(result.scalars().all())
    return select_default_workspace_membership(
        memberships,
        getattr(user, "default_workspace_id", None),
    )


async def require_default_workspace_membership_for_user(
    db: AsyncSession,
    user: User,
) -> WorkspaceMembership:
    """Get the user's default active workspace membership or raise a validation error."""
    membership = await get_default_workspace_membership_for_user(db, user)
    if membership:
        return membership

    raise AppValidationError("No active workspace. Please select or create a workspace.")


async def get_default_workspace_for_user(db: AsyncSession, user: User) -> Workspace | None:
    """Get the user's default active workspace.

    Returns the user's configured default workspace when the user still has an
    active membership for it, otherwise the personal workspace, otherwise the
    oldest active membership's workspace. Returns None only if the user has no
    active workspace memberships.
    """
    membership = await get_default_workspace_membership_for_user(db, user)
    return membership.workspace if membership else None
