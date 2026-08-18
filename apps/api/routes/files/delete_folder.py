# apps/api/routes/files/delete_folder.py

"""Route for deleting a workspace file folder and its contents."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request, Response, status

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep
from services.files import delete_folder as delete_folder_service

router = APIRouter()


@router.delete("/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    folder_id: Annotated[UUID, Path()],
) -> Response:
    workspace, membership = workspace_context
    await delete_folder_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        membership=membership,
        folder_id=folder_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
