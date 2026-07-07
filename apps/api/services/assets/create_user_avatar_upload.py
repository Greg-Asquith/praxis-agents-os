# apps/api/services/assets/create_user_avatar_upload.py

"""Create a direct-upload grant for the authenticated user's avatar."""

from models.user import User
from services.assets.domain import AssetUploadGrant, AssetUploadRequest
from services.assets.utils import USER_AVATAR_ASSET_SPEC, create_asset_upload


async def create_user_avatar_upload(
    *,
    actor: User,
    payload: AssetUploadRequest,
) -> AssetUploadGrant:
    return await create_asset_upload(
        USER_AVATAR_ASSET_SPEC,
        actor=actor,
        owner_id=actor.id,
        payload=payload,
        target_user_id=actor.id,
    )
