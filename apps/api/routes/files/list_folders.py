# apps/api/routes/files/list_folders.py

"""Route for listing workspace file folders."""

from fastapi import APIRouter

from core.dependencies import AsyncDbSessionDep, CurrentWorkspaceDep
from services.files import list_folders as list_folders_service
from services.files.domain import FileFolderListResponse

router = APIRouter()


@router.get("/folders")
async def list_folders(
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
) -> FileFolderListResponse:
    workspace, _membership = workspace_context
    return await list_folders_service(db, workspace=workspace)
