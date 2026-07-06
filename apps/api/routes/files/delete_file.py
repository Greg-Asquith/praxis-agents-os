# apps/api/routes/files/delete_file.py

"""Route for soft-deleting a workspace file."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request, Response, status

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.files import delete_file as delete_file_service

router = APIRouter()


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    file_id: Annotated[UUID, Path()],
) -> Response:
    workspace, membership = workspace_context
    await delete_file_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        file_id=file_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
