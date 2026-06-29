# apps/api/routes/users/list_users.py

"""Route for listing users."""

from typing import Annotated

from fastapi import APIRouter, Query

from core.dependencies import AsyncDbSessionDep
from routes.users.dependencies import SuperAdminDep
from services.users import list_users as list_users_service
from services.users.schemas import UsersListResponse

router = APIRouter()


@router.get("/")
async def list_users(
    db: AsyncDbSessionDep,
    _: SuperAdminDep,
    q: Annotated[str | None, Query(max_length=255)] = None,
    include_deleted: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> UsersListResponse:
    return await list_users_service(
        db,
        q=q,
        include_deleted=include_deleted,
        limit=limit,
        offset=offset,
    )
