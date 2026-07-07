# apps/api/services/assets/create_workspace_icon_upload.py

"""Create a direct-upload grant for a workspace icon."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from services.assets.domain import AssetUploadGrant, AssetUploadRequest
from services.assets.utils import WORKSPACE_ICON_ASSET_SPEC as SPEC, create_asset_upload
from services.workspaces.utils import MANAGER_ROLES as ROLES, require_workspace_role as require_role


async def create_workspace_icon_upload(
    db: AsyncSession,
    *,
    actor: User,
    workspace_id: UUID,
    payload: AssetUploadRequest,
) -> AssetUploadGrant:
    await require_role(db, actor=actor, workspace_id=workspace_id, allowed_roles=ROLES)
    return await create_asset_upload(
        SPEC,
        actor=actor,
        owner_id=workspace_id,
        payload=payload,
        workspace_id=workspace_id,
    )
