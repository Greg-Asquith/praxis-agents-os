# apps/api/routes/workspaces/create_workspace.py

"""Route for creating a workspace."""

from fastapi import APIRouter, Request, status

from core.dependencies import AsyncDbSessionDep, CurrentUserDep
from services.workspaces import create_workspace as create_workspace_service
from services.workspaces.schemas import WorkspaceCreateRequest, WorkspaceRead

router = APIRouter()


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_workspace(
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    payload: WorkspaceCreateRequest,
) -> WorkspaceRead:
    return await create_workspace_service(db, request=request, actor=actor, payload=payload)
