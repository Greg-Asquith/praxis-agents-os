# apps/api/services/assets/delete_user_avatar.py

"""Delete the authenticated user's managed avatar."""

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from services.assets.utils import USER_AVATAR_ASSET_SPEC, delete_user_asset
from services.auth.schemas import AuthUser


async def delete_user_avatar(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
) -> AuthUser:
    return await delete_user_asset(
        db,
        USER_AVATAR_ASSET_SPEC,
        request=request,
        actor=actor,
    )
