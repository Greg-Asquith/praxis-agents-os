# apps/api/routes/files/create_file_upload.py

"""Route for creating workspace file upload grants."""

from fastapi import APIRouter

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.files import create_file_upload as create_upload_service
from services.files.domain import FileUploadRequest, FileUploadResult

router = APIRouter()


@router.post("/uploads")
async def create_file_upload(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    payload: FileUploadRequest,
) -> FileUploadResult:
    workspace, membership = workspace_context
    return await create_upload_service(
        db,
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=payload,
    )
