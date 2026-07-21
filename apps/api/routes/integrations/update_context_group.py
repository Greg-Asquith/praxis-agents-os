# apps/api/routes/integrations/update_context_group.py

"""Update an integration context group."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_editor
from services.integrations.context import update_context_group as update_context_group_service
from services.integrations.context.schemas import ContextGroupRead, ContextGroupUpdateRequest

router = APIRouter(dependencies=[Depends(require_editor)])


@router.patch("/context-groups/{group_id}")
async def update_context_group(
    group_id: Annotated[UUID, Path()],
    payload: ContextGroupUpdateRequest,
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> ContextGroupRead:
    workspace, _membership = workspace_context
    return await update_context_group_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        group_id=group_id,
        payload=payload,
    )
