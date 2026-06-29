# apps/api/routes/auth/change_password.py

"""Route for changing the current user's password."""

from fastapi import APIRouter, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.auth import change_password as change_password_service
from services.auth.schemas import MessageResponse, PasswordChangeRequest

router = APIRouter()


@router.put("/password")
async def change_password(
    request: Request,
    db: AsyncDbSessionDep,
    user: CurrentUserDep,
    payload: PasswordChangeRequest,
) -> MessageResponse:
    return await change_password_service(db, request=request, user=user, payload=payload)
