# apps/api/routes/files/get_file_revision_content.py

"""Route for fetching editable text content from one file revision."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.files import get_file_revision_content as get_revision_content_service
from services.files.domain import FileRevisionContentRead

router = APIRouter()


@router.get("/{file_id}/revisions/{revision_id}/content")
async def get_file_revision_content(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    file_id: Annotated[UUID, Path()],
    revision_id: Annotated[UUID, Path()],
) -> FileRevisionContentRead:
    workspace, _membership = workspace_context
    return await get_revision_content_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        file_id=file_id,
        revision_id=revision_id,
    )
