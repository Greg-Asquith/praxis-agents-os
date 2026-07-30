# apps/api/routes/integrations/clear_context.py

"""Clear one conversation's active integration context selection."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, Response, status

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_read
from services.integrations.context import clear_active_context_selection

router = APIRouter(dependencies=[Depends(require_read)])


@router.delete(
    "/conversations/{conversation_id}/context",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def clear_context(
    conversation_id: Annotated[UUID, Path()],
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> Response:
    workspace, _membership = workspace_context
    await clear_active_context_selection(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
