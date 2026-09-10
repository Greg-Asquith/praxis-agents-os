# apps/api/routes/files/platform/get_file.py

"""Returns one platform File for management."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.files.domain import FileRead
from services.files.platform import get_file as get_file_service

router = APIRouter()


@router.get("/{file_id}")
async def get_file(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    file_id: Annotated[UUID, Path()],
) -> FileRead:
    return await get_file_service(
        db,
        actor=actor,
        file_id=file_id,
    )
