# apps/api/routes/files/platform/list_files.py

"""Route for listing platform files."""

from typing import Annotated

from fastapi import APIRouter, Query

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.files.domain import FileListResponse
from services.files.platform import list_files as list_files_service

router = APIRouter()


@router.get("/")
async def list_files(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    search: Annotated[str | None, Query(max_length=255)] = None,
    sort_by: Annotated[str, Query(max_length=32)] = "created_at",
    sort_direction: Annotated[str, Query(max_length=4)] = "desc",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> FileListResponse:
    return await list_files_service(
        db,
        actor=actor,
        limit=limit,
        offset=offset,
        search=search,
        sort_by=sort_by,
        sort_direction=sort_direction,
    )
