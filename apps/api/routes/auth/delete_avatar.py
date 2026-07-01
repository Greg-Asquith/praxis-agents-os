# apps/api/routes/auth/delete_upload.py

"""Route for deleting the current user's avatar."""

from fastapi import APIRouter, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.assets import delete_user_avatar
from services.auth.schemas import AuthUser

router = APIRouter()


@router.delete("/me/avatar")
async def delete_avatar(
    request: Request,
    db: AsyncDbSessionDep,
    user: CurrentUserDep,
) -> AuthUser:
    return await delete_user_avatar(db, request=request, actor=user)
