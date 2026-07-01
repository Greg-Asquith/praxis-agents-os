# apps/api/services/assets/create_workspace_icon_upload.py

"""Create a direct-upload grant for a workspace icon."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.user import User
from services.assets.domain import AssetKind, AssetUploadGrant, AssetUploadRequest
from services.assets.tokens import create_asset_upload_token
from services.assets.utils import (
    allowed_workspace_icon_content_types,
    public_asset_ref,
    validate_upload_metadata,
)
from services.storage.factory import get_storage_provider
from services.workspaces.utils import MANAGER_ROLES, require_workspace_role


async def create_workspace_icon_upload(
    db: AsyncSession,
    *,
    actor: User,
    workspace_id: UUID,
    payload: AssetUploadRequest,
) -> AssetUploadGrant:
    await require_workspace_role(
        db,
        actor=actor,
        workspace_id=workspace_id,
        allowed_roles=MANAGER_ROLES,
    )
    max_size_bytes = settings.MAX_FILE_SIZE_ICON
    content_type = validate_upload_metadata(
        filename=payload.filename,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
        allowed_content_types=allowed_workspace_icon_content_types(),
        max_size_bytes=max_size_bytes,
        asset_label="workspace icon",
    )
    ref = public_asset_ref(f"workspaces/{workspace_id}/icon", content_type=content_type)
    provider = get_storage_provider()
    upload = await provider.create_signed_upload(
        ref,
        content_type=content_type,
        expires_in=timedelta(minutes=10),
    )
    upload_token, expires_at = create_asset_upload_token(
        kind=AssetKind.WORKSPACE_ICON,
        actor_user_id=actor.id,
        workspace_id=workspace_id,
        ref=ref,
        content_type=content_type,
        max_size_bytes=max_size_bytes,
    )
    return AssetUploadGrant(
        upload=upload,
        upload_token=upload_token,
        max_size_bytes=max_size_bytes,
        expires_at=expires_at,
    )
