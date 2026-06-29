# apps/api/routes/users/set_user_password.py

"""Route for setting a user's password."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep
from routes.users.dependencies import SuperAdminDep
from services.users import set_user_password as set_user_password_service
from services.users.schemas import UserPasswordSetRequest, UserRead

router = APIRouter()


@router.put("/{user_id}/password")
async def set_user_password(
    request: Request,
    db: AsyncDbSessionDep,
    actor: SuperAdminDep,
    user_id: Annotated[UUID, Path()],
    payload: UserPasswordSetRequest,
) -> UserRead:
    return await set_user_password_service(
        db,
        request=request,
        actor=actor,
        user_id=user_id,
        payload=payload,
    )
