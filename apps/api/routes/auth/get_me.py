# apps/api/routes/auth/get_me.py

"""Route for reading the authenticated user."""

from fastapi import APIRouter

from core.dependencies import CurrentUserDep
from services.auth.schemas import AuthUser

router = APIRouter()


@router.get("/me")
async def get_me(user: CurrentUserDep) -> AuthUser:
    return AuthUser.from_user(user)
