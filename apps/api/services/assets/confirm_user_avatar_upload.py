# apps/api/services/assets/confirm_user_avatar_upload.py

"""Confirm an uploaded avatar and attach it to the authenticated user."""

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from services.assets.domain import AssetConfirmRequest
from services.assets.utils import USER_AVATAR_ASSET_SPEC, confirm_user_asset
from services.auth.schemas import AuthUser


async def confirm_user_avatar_upload(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    payload: AssetConfirmRequest,
) -> AuthUser:
    return await confirm_user_asset(
        db,
        USER_AVATAR_ASSET_SPEC,
        request=request,
        actor=actor,
        payload=payload,
    )
