# apps/api/routes/files/create_folder.py

"""Route for creating a workspace file folder."""

from fastapi import APIRouter, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.files import create_folder as create_folder_service
from services.files.domain import FileFolderCreateRequest, FileFolderRead

router = APIRouter()


@router.post("/folders")
async def create_folder(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    payload: FileFolderCreateRequest,
) -> FileFolderRead:
    workspace, membership = workspace_context
    return await create_folder_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=payload,
    )
