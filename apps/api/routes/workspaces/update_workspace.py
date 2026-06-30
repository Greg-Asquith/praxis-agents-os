# apps/api/routes/workspaces/update_workspace.py

"""Route for updating a workspace."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.workspaces import update_workspace as update_workspace_service
from services.workspaces.schemas import WorkspaceRead, WorkspaceUpdateRequest

router = APIRouter()


@router.patch("/{workspace_id}")
async def update_workspace(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_id: Annotated[UUID, Path()],
    payload: WorkspaceUpdateRequest,
) -> WorkspaceRead:
    return await update_workspace_service(
        db,
        request=request,
        actor=actor,
        workspace_id=workspace_id,
        payload=payload,
    )
