# apps/api/routes/files/list_files.py

"""Route for listing workspace files."""

from typing import Annotated

from fastapi import APIRouter, Query

from core.dependencies import AsyncDbSessionDep, CurrentWorkspaceDep
from services.files import list_files as list_files_service
from services.files.domain import FileListResponse

router = APIRouter()


@router.get("/")
async def list_files(
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
    category: Annotated[str | None, Query(max_length=32)] = None,
    search: Annotated[str | None, Query(max_length=255)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> FileListResponse:
    workspace, _membership = workspace_context
    return await list_files_service(
        db,
        workspace=workspace,
        category=category,
        search=search,
        limit=limit,
        offset=offset,
    )
