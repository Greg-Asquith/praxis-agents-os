# apps/api/routes/files/get_file.py

"""Route for fetching one workspace file."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentWorkspaceDep
from services.files import get_file as get_file_service
from services.files.domain import FileRead

router = APIRouter()


@router.get("/{file_id}")
async def get_file(
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
    file_id: Annotated[UUID, Path()],
) -> FileRead:
    workspace, _membership = workspace_context
    return await get_file_service(db, workspace=workspace, file_id=file_id)
