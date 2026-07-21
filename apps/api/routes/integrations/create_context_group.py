# apps/api/routes/integrations/create_context_group.py

"""Create an integration context group."""

from fastapi import APIRouter, Depends, Request, status

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_editor
from services.integrations.context import create_context_group as create_context_group_service
from services.integrations.context.schemas import ContextGroupCreateRequest, ContextGroupRead

router = APIRouter(dependencies=[Depends(require_editor)])


@router.post("/context-groups", status_code=status.HTTP_201_CREATED)
async def create_context_group(
    payload: ContextGroupCreateRequest,
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> ContextGroupRead:
    workspace, _membership = workspace_context
    return await create_context_group_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        payload=payload,
    )
