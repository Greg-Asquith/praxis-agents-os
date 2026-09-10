# apps/api/routes/files/platform/update_file.py

"""Updates platform File metadata."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.files.domain import FileRead, PlatformFileUpdateRequest
from services.files.platform import update_file as update_file_service

router = APIRouter()


@router.patch("/{file_id}")
async def update_file(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    file_id: Annotated[UUID, Path()],
    payload: PlatformFileUpdateRequest,
) -> FileRead:
    return await update_file_service(
        db,
        actor=actor,
        file_id=file_id,
        request=request,
        payload=payload,
    )
