# apps/api/routes/files/move_files.py

"""Route for moving workspace files between folders."""

from fastapi import APIRouter, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.files import move_files as move_files_service
from services.files.domain import FileMoveRequest, FileMoveResponse

router = APIRouter()


@router.post("/move")
async def move_files(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    payload: FileMoveRequest,
) -> FileMoveResponse:
    workspace, membership = workspace_context
    return await move_files_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=payload,
    )
