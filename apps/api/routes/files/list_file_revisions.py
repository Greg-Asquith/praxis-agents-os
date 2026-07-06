# apps/api/routes/files/list_file_revisions.py

"""Route for listing workspace file revisions."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentWorkspaceDep
from services.files import list_file_revisions as list_file_revisions_service
from services.files.domain import FileRevisionsListResponse

router = APIRouter()


@router.get("/{file_id}/revisions")
async def list_file_revisions(
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
    file_id: Annotated[UUID, Path()],
) -> FileRevisionsListResponse:
    workspace, _membership = workspace_context
    return await list_file_revisions_service(db, workspace=workspace, file_id=file_id)
