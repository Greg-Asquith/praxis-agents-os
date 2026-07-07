# apps/api/routes/files/create_file_preview.py

"""Route for creating workspace file preview grants."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentWorkspaceDep
from services.files import create_file_preview as create_file_preview_service
from services.files.domain import FilePreviewGrant

router = APIRouter()


@router.post("/{file_id}/preview")
async def create_file_preview(
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
    file_id: Annotated[UUID, Path()],
) -> FilePreviewGrant:
    workspace, _membership = workspace_context
    return await create_file_preview_service(
        db,
        workspace=workspace,
        file_id=file_id,
    )
