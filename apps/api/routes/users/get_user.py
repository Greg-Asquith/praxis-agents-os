# apps/api/routes/users/get_user.py

"""Route for fetching a user."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query

from core.dependencies import AsyncDbSessionDep
from routes.users.dependencies import SuperAdminDep
from services.users import get_user as get_user_service
from services.users.schemas import UserRead

router = APIRouter()


@router.get("/{user_id}")
async def get_user(
    db: AsyncDbSessionDep,
    _: SuperAdminDep,
    user_id: Annotated[UUID, Path()],
    include_deleted: Annotated[bool, Query()] = False,
) -> UserRead:
    return await get_user_service(db, user_id=user_id, include_deleted=include_deleted)
