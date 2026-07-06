# apps/api/routes/files/purge_file.py

"""Route for hard-deleting a workspace file."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request, Response, status

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.files import purge_file as purge_file_service

router = APIRouter()


@router.post("/{file_id}/purge", status_code=status.HTTP_204_NO_CONTENT)
async def purge_file(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    file_id: Annotated[UUID, Path()],
) -> Response:
    workspace, membership = workspace_context
    await purge_file_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        file_id=file_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
