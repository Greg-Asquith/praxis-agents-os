# apps/api/custom/hooks.py

"""Deployment hooks that core calls inside its own transaction.

Import implementations inside each function, because core auth and workspace
services import this module while they load. An exception fails the operation.
"""

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.workspace import Workspace, WorkspaceMembership


async def after_sign_in(db: AsyncSession, *, user: User, request: Request | None) -> None:
    """Called when a user completes a full sign-in, after any two-factor step."""


async def after_workspace_created(
    db: AsyncSession, *, workspace: Workspace, actor: User, request: Request | None
) -> None:
    """Called when a workspace is created, with tenant context set to it."""


async def before_membership_change(
    db: AsyncSession, *, actor: User, membership: WorkspaceMembership, new_role: str | None
) -> None:
    """Called before a membership changes role, or is removed when `new_role` is None.

    Raise `AuthorizationError` to reject the change.
    """
