# apps/api/services/assets/confirm_workspace_icon_upload.py

"""Confirm an uploaded workspace icon and attach it to the workspace."""

from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from services.assets.domain import AssetConfirmRequest
from services.assets.utils import WORKSPACE_ICON_ASSET_SPEC as SPEC, confirm_workspace_asset
from services.workspaces.schemas import WorkspaceRead
from services.workspaces.utils import MANAGER_ROLES as ROLES, require_workspace_role as require


async def confirm_workspace_icon_upload(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace_id: UUID,
    payload: AssetConfirmRequest,
) -> WorkspaceRead:
    workspace, membership = await require(
        db, actor=actor, workspace_id=workspace_id, allowed_roles=ROLES
    )
    return await confirm_workspace_asset(
        db,
        SPEC,
        request=request,
        actor=actor,
        workspace=workspace,
        current_user_role=membership.role,
        payload=payload,
    )
