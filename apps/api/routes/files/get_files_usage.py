# apps/api/routes/files/get_files_usage.py

"""Route for workspace file storage usage."""

from fastapi import APIRouter

from core.dependencies import AsyncDbSessionDep, CurrentWorkspaceDep
from services.files import get_files_usage as get_files_usage_service
from services.files.domain import FilesUsageResponse

router = APIRouter()


@router.get("/usage")
async def get_files_usage(
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
) -> FilesUsageResponse:
    workspace, _membership = workspace_context
    return await get_files_usage_service(db, workspace=workspace)
