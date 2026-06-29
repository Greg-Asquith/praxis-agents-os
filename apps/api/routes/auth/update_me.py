# apps/api/routes/auth/update_me.py

"""Route for updating the authenticated user."""

from fastapi import APIRouter, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.auth import update_current_user
from services.auth.schemas import AuthUser, CurrentUserUpdateRequest

router = APIRouter()


@router.patch("/me")
async def update_me(
    request: Request,
    db: AsyncDbSessionDep,
    user: CurrentUserDep,
    payload: CurrentUserUpdateRequest,
) -> AuthUser:
    return await update_current_user(db, request=request, user=user, payload=payload)
