# apps/api/routes/workspaces/delete_icon.py

"""Route for deleting a workspace icon."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.assets import delete_workspace_icon
from services.workspaces.schemas import WorkspaceRead

router = APIRouter()


@router.delete("/{workspace_id}/icon")
async def delete_icon(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_id: Annotated[UUID, Path()],
) -> WorkspaceRead:
    return await delete_workspace_icon(
        db,
        request=request,
        actor=actor,
        workspace_id=workspace_id,
    )
