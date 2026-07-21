# apps/api/routes/integrations/delete_context_group.py

"""Delete an integration context group."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, Response, status

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_editor
from services.integrations.context import delete_context_group as delete_context_group_service

router = APIRouter(dependencies=[Depends(require_editor)])


@router.delete("/context-groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_context_group(
    group_id: Annotated[UUID, Path()],
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> Response:
    workspace, _membership = workspace_context
    await delete_context_group_service(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        group_id=group_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
