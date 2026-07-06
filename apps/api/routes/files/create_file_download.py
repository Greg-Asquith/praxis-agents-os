# apps/api/routes/files/create_file_download.py

"""Route for creating workspace file download grants."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.files import create_file_download as create_file_download_service
from services.files.domain import FileDownloadGrant, FileDownloadRequest

router = APIRouter()


@router.post("/{file_id}/download")
async def create_file_download(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    file_id: Annotated[UUID, Path()],
    payload: FileDownloadRequest | None = None,
) -> FileDownloadGrant:
    workspace, _membership = workspace_context
    return await create_file_download_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        file_id=file_id,
        payload=payload or FileDownloadRequest(),
    )
