# apps/api/routes/auth/create_avatar_upload.py

"""Route for creating a current-user avatar upload grant."""

from fastapi import APIRouter

from core.dependencies import CurrentUserDep
from services.assets import create_user_avatar_upload
from services.assets.domain import AssetUploadGrant, AssetUploadRequest

router = APIRouter()


@router.post("/me/avatar/upload")
async def create_avatar_upload(
    user: CurrentUserDep,
    payload: AssetUploadRequest,
) -> AssetUploadGrant:
    return await create_user_avatar_upload(actor=user, payload=payload)
