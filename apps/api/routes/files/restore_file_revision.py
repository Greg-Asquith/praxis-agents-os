# apps/api/routes/files/restore_file_revision.py

"""Route for restoring a workspace file revision."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.files import restore_file_revision as restore_file_revision_service
from services.files.domain import FileRead, FileRestoreRequest

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
    workspace, membership = workspace_context
    return await restore_file_revision_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        file_id=file_id,
        payload=payload,
    )
