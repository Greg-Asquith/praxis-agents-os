# apps/api/services/workspaces/get_workspace.py

"""Read one workspace visible to the authenticated user."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from services.workspaces.schemas import WorkspaceRead
from services.workspaces.utils import READ_ROLES, require_workspace_role


async def get_workspace(
    db: AsyncSession,
    *,
    actor: User,
    workspace_id: UUID,
) -> WorkspaceRead:
    workspace, membership = await require_workspace_role(
        db,
        actor=actor,
        workspace_id=workspace_id,
        allowed_roles=READ_ROLES,
    )
    return WorkspaceRead.from_workspace(workspace, current_user_role=membership.role)
