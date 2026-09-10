# apps/api/routes/files/platform/list_file_revisions.py

"""Route for listing platform file revisions."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.files.domain import FileRevisionsListResponse
from services.files.platform import list_file_revisions as list_file_revisions_service

router = APIRouter()


@router.get("/{file_id}/revisions")
async def list_file_revisions(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    file_id: Annotated[UUID, Path()],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> FileRevisionsListResponse:
    return await list_file_revisions_service(
        db, actor=actor, file_id=file_id, limit=limit, offset=offset
    )
