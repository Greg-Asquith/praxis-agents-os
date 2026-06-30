# apps/api/services/workspaces/list_workspaces.py

"""List workspaces visible to the authenticated user."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.workspaces.schemas import WorkspaceRead, WorkspacesListResponse


async def list_workspaces(
    db: AsyncSession,
    *,
    actor: User,
    limit: int,
    offset: int,
) -> WorkspacesListResponse:
    stmt = (
        select(Workspace, WorkspaceMembership)
        .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
        .where(
            WorkspaceMembership.user_id == actor.id,
            WorkspaceMembership.deleted.is_(False),
            Workspace.deleted.is_(False),
        )
    )
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(
        stmt.order_by(Workspace.is_personal.desc(), Workspace.name.asc())
        .limit(limit)
        .offset(offset)
    )
    return WorkspacesListResponse(
        workspaces=[
            WorkspaceRead.from_workspace(workspace, current_user_role=membership.role)
            for workspace, membership in result.all()
        ],
        total=total or 0,
        limit=limit,
        offset=offset,
    )
