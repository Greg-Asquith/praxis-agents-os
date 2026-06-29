# apps/api/routes/users/update_user.py

"""Route for updating a user."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep
from routes.users.dependencies import SuperAdminDep
from services.users import update_user as update_user_service
from services.users.schemas import UserRead, UserUpdateRequest

router = APIRouter()


@router.patch("/{user_id}")
async def update_user(
    request: Request,
    db: AsyncDbSessionDep,
    actor: SuperAdminDep,
    user_id: Annotated[UUID, Path()],
    payload: UserUpdateRequest,
) -> UserRead:
    return await update_user_service(
        db,
        request=request,
        actor=actor,
        user_id=user_id,
        payload=payload,
    )
