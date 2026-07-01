# apps/api/services/assets/create_user_avatar_upload.py

"""Create a direct-upload grant for the authenticated user's avatar."""

from datetime import timedelta

from core.settings import settings
from models.user import User
from services.assets.domain import AssetKind, AssetUploadGrant, AssetUploadRequest
from services.assets.tokens import create_asset_upload_token
from services.assets.utils import (
    allowed_avatar_content_types,
    public_asset_ref,
    validate_upload_metadata,
)
from services.storage.factory import get_storage_provider


async def create_user_avatar_upload(
    *,
    actor: User,
    payload: AssetUploadRequest,
) -> AssetUploadGrant:
    max_size_bytes = settings.MAX_FILE_SIZE_AVATAR
    content_type = validate_upload_metadata(
        filename=payload.filename,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
        allowed_content_types=allowed_avatar_content_types(),
        max_size_bytes=max_size_bytes,
        asset_label="avatar",
    )
    ref = public_asset_ref(f"users/{actor.id}/avatar", content_type=content_type)
    provider = get_storage_provider()
    upload = await provider.create_signed_upload(
        ref,
        content_type=content_type,
        expires_in=timedelta(minutes=10),
    )
    upload_token, expires_at = create_asset_upload_token(
        kind=AssetKind.USER_AVATAR,
        actor_user_id=actor.id,
        target_user_id=actor.id,
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
