# apps/api/services/workspaces/memberships/get_membership.py

"""Read one workspace membership."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from services.workspaces.memberships.utils import get_membership_or_raise
from services.workspaces.schemas import WorkspaceMembershipRead
from services.workspaces.utils import READ_ROLES, require_workspace_role


async def get_membership(
    db: AsyncSession,
    *,
    actor: User,
    workspace_id: UUID,
    membership_id: UUID,
) -> WorkspaceMembershipRead:
    await require_workspace_role(
        db,
        actor=actor,
        workspace_id=workspace_id,
        allowed_roles=READ_ROLES,
    )
    membership = await get_membership_or_raise(
        db,
        workspace_id=workspace_id,
        membership_id=membership_id,
    )
    return WorkspaceMembershipRead.from_membership(membership)
