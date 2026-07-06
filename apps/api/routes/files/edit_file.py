# apps/api/routes/files/edit_file.py

"""Route for editing workspace file text content."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.files import edit_file as edit_file_service
from services.files.domain import FileEditRequest, FileRead

router = APIRouter()


@router.put("/{file_id}/content")
async def edit_file(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    file_id: Annotated[UUID, Path()],
    payload: FileEditRequest,
) -> FileRead:
    workspace, membership = workspace_context
    return await edit_file_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        file_id=file_id,
        payload=payload,
    )
