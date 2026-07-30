# apps/api/routes/integrations/set_context.py

"""Set one conversation's active integration context selection."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_read
from services.integrations.context import set_active_context_selection
from services.integrations.context.schemas import ActiveContextRead, ActiveContextSelectionValue

router = APIRouter(dependencies=[Depends(require_read)])


@router.put("/conversations/{conversation_id}/context")
async def set_context(
    conversation_id: Annotated[UUID, Path()],
    payload: ActiveContextSelectionValue,
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> ActiveContextRead:
    workspace, _membership = workspace_context
    selection = await set_active_context_selection(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation_id,
        selection=payload,
    )
    return ActiveContextRead(selection=ActiveContextSelectionValue.from_selection(selection))
