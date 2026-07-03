# apps/api/routes/auth/get_me.py

"""Route for reading the authenticated user."""

from fastapi import APIRouter

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.auth.schemas import AuthUser
from services.auth.utils import build_auth_user

router = APIRouter()


@router.get("/me")
async def get_me(db: AsyncDbSessionDep, user: CurrentUserDep) -> AuthUser:
    return await build_auth_user(db, user)
