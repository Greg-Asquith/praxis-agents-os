# apps/api/routes/users/delete_user.py

"""Route for deleting a user."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request, Response, status

from core.dependencies import AsyncDbSessionDep
from routes.users.dependencies import SuperAdminDep
from services.users import delete_user as delete_user_service

router = APIRouter()


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    request: Request,
    response: Response,
    db: AsyncDbSessionDep,
    actor: SuperAdminDep,
    user_id: Annotated[UUID, Path()],
) -> None:
    await delete_user_service(db, request=request, actor=actor, user_id=user_id)
    response.status_code = status.HTTP_204_NO_CONTENT
