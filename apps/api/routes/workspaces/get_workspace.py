# apps/api/routes/workspaces/get_workspace.py

"""Route for reading a workspace."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.workspaces import get_workspace as get_workspace_service
from services.workspaces.schemas import WorkspaceRead

router = APIRouter()


@router.get("/{workspace_id}")
async def get_workspace(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_id: Annotated[UUID, Path()],
) -> WorkspaceRead:
    return await get_workspace_service(db, actor=actor, workspace_id=workspace_id)
