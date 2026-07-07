# apps/api/services/assets/delete_workspace_icon.py

"""Delete a workspace's managed icon."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from services.assets.utils import WORKSPACE_ICON_ASSET_SPEC as SPEC, delete_workspace_asset
from services.workspaces.schemas import WorkspaceRead
from services.workspaces.utils import MANAGER_ROLES as ROLES, require_workspace_role as require


async def delete_workspace_icon(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace_id: UUID,
) -> WorkspaceRead:
    workspace, membership = await require(
        db, actor=actor, workspace_id=workspace_id, allowed_roles=ROLES
    )
    return await delete_workspace_asset(
        db,
        SPEC,
        request=request,
        actor=actor,
        workspace=workspace,
        current_user_role=membership.role,
    )
