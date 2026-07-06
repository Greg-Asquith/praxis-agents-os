# apps/api/routes/files/confirm_file_upload.py

"""Route for confirming workspace file uploads."""

from fastapi import APIRouter, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.files import confirm_file_upload as confirm_upload_service
from services.files.domain import FileConfirmRequest, FileRead

router = APIRouter()


@router.post("/uploads/confirm")
async def confirm_file_upload(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    payload: FileConfirmRequest,
) -> FileRead:
    workspace, membership = workspace_context
    return await confirm_upload_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=payload,
    )
