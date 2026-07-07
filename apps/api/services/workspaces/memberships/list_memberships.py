# apps/api/services/workspaces/memberships/list_memberships.py

"""List members in a workspace."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.user import User
from models.workspace import WorkspaceMembership
from services.workspaces.schemas import (
    WorkspaceMembershipRead,
    WorkspaceMembershipsListResponse,
)
from services.workspaces.utils import READ_ROLES, require_workspace_role
from utils.pagination import paginate


async def list_memberships(
    db: AsyncSession,
    *,
    actor: User,
    workspace_id: UUID,
    limit: int,
    offset: int,
) -> WorkspaceMembershipsListResponse:
    await require_workspace_role(
        db,
        actor=actor,
        workspace_id=workspace_id,
        allowed_roles=READ_ROLES,
    )
    stmt = (
        select(WorkspaceMembership)
        .options(selectinload(WorkspaceMembership.user))
        .where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.deleted.is_(False),
        )
    )
    memberships, total = await paginate(
        db,
        stmt,
        WorkspaceMembership.created_at.asc(),
        limit=limit,
        offset=offset,
    )
    return WorkspaceMembershipsListResponse(
        memberships=[
            WorkspaceMembershipRead.from_membership(membership) for membership in memberships
        ],
        total=total or 0,
        limit=limit,
        offset=offset,
    )
