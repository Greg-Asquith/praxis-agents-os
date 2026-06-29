# apps/api/routes/users/create_user.py

"""Route for creating a user."""

from fastapi import APIRouter, Request, status

from core.dependencies import AsyncDbSessionDep
from routes.users.dependencies import SuperAdminDep
from services.users import create_user as create_user_service
from services.users.schemas import UserCreateRequest, UserRead

router = APIRouter()


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_user(
    request: Request,
    db: AsyncDbSessionDep,
    actor: SuperAdminDep,
    payload: UserCreateRequest,
) -> UserRead:
    return await create_user_service(db, request=request, actor=actor, payload=payload)
