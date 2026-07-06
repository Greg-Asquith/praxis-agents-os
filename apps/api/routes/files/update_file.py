# apps/api/routes/files/update_file.py

"""Route for updating workspace file metadata."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.files import update_file as update_file_service
from services.files.domain import FileRead, FileUpdateRequest

router = APIRouter()


@router.patch("/{file_id}")
async def update_file(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    file_id: Annotated[UUID, Path()],
    payload: FileUpdateRequest,
) -> FileRead:
    workspace, membership = workspace_context
    return await update_file_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        file_id=file_id,
        payload=payload,
    )
