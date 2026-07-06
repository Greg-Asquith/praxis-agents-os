# apps/api/routes/files/get_files_processing.py

"""Route for workspace file processing summary."""

from fastapi import APIRouter

from core.dependencies import AsyncDbSessionDep, CurrentWorkspaceDep
from services.files import get_files_processing_summary as get_files_processing_summary_service
from services.files.domain import FilesProcessingSummary

router = APIRouter()


@router.get("/processing")
async def get_files_processing(
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
) -> FilesProcessingSummary:
    workspace, _membership = workspace_context
    return await get_files_processing_summary_service(db, workspace=workspace)
