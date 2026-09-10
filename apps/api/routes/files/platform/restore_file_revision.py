# apps/api/routes/files/platform/restore_file_revision.py

"""Restores a platform File revision."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.files.domain import FileRead, FileRestoreRequest
from services.files.platform import restore_file_revision as restore_file_revision_service

router = APIRouter()


@router.post("/{file_id}/restore")
async def restore_file_revision(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    file_id: Annotated[UUID, Path()],
    payload: FileRestoreRequest,
) -> FileRead:
    return await restore_file_revision_service(
        db,
        actor=actor,
        file_id=file_id,
        request=request,
        payload=payload,
    )
