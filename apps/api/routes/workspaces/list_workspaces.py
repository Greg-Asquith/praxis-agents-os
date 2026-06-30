# apps/api/routes/workspaces/list_workspaces.py

"""Route for listing workspaces."""

from typing import Annotated

from fastapi import APIRouter, Query

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.workspaces import list_workspaces as list_workspaces_service
from services.workspaces.schemas import WorkspacesListResponse

router = APIRouter()


@router.get("/")
async def list_workspaces(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> WorkspacesListResponse:
    return await list_workspaces_service(db, actor=actor, limit=limit, offset=offset)
