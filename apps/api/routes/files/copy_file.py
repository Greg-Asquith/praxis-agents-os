# apps/api/routes/files/copy_file.py

"""Route for an independent workspace copy of a platform File."""

from uuid import UUID

from fastapi import APIRouter, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.files.copy_file import copy_file as copy_file_service
from services.files.domain import FileCopyRequest, FileRead

router = APIRouter()


@router.post("/{file_id}/copy")
async def copy_file(
    file_id: UUID,
    payload: FileCopyRequest,
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> FileRead:
    workspace, membership = workspace_context
    return await copy_file_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        file_id=file_id,
        payload=payload,
    )
