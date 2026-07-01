# apps/api/routes/auth/confirm_avatar_upload.py

"""Route for confirming a current-user avatar upload."""

from fastapi import APIRouter, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.assets import confirm_user_avatar_upload
from services.assets.domain import AssetConfirmRequest
from services.auth.schemas import AuthUser

router = APIRouter()


@router.post("/me/avatar/confirm")
async def confirm_avatar_upload(
    request: Request,
    db: AsyncDbSessionDep,
    user: CurrentUserDep,
    payload: AssetConfirmRequest,
) -> AuthUser:
    return await confirm_user_avatar_upload(
        db,
        request=request,
        actor=user,
        payload=payload,
    )
