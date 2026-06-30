# apps/api/routes/workspaces/delete_workspace.py

"""Route for deleting a workspace."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request, Response, status

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.workspaces import delete_workspace as delete_workspace_service

router = APIRouter()


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    request: Request,
    response: Response,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_id: Annotated[UUID, Path()],
) -> None:
    await delete_workspace_service(db, request=request, actor=actor, workspace_id=workspace_id)
    response.status_code = status.HTTP_204_NO_CONTENT
