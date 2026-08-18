# apps/api/routes/files/update_folder.py

"""Route for updating a workspace file folder."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.files import update_folder as update_folder_service
from services.files.domain import FileFolderRead, FileFolderUpdateRequest

router = APIRouter()


@router.patch("/folders/{folder_id}")
async def update_folder(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    folder_id: Annotated[UUID, Path()],
    payload: FileFolderUpdateRequest,
) -> FileFolderRead:
    workspace, membership = workspace_context
    return await update_folder_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        folder_id=folder_id,
        payload=payload,
    )
