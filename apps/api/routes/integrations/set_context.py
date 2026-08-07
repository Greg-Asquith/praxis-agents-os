# apps/api/routes/integrations/set_context.py

"""Set one conversation's active integration context selection."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_read
from services.integrations.context import (
    resolve_active_context_targets,
    set_active_context_selection,
)
from services.integrations.context.schemas import (
    ActiveContextRead,
    ActiveContextSelectionValue,
    ActiveContextTargets,
)

router = APIRouter(dependencies=[Depends(require_read)])


@router.put("/conversations/{conversation_id}/context")
async def set_context(
    conversation_id: Annotated[UUID, Path()],
    payload: ActiveContextTargets,
    request: Request,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> ActiveContextRead:
    workspace, _membership = workspace_context
    selections = await set_active_context_selection(
        db,
        request=request,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation_id,
        targets=payload,
    )
    targets = [ActiveContextSelectionValue.from_selection(selection) for selection in selections]
    resolved = await resolve_active_context_targets(
        db,
        selections=targets,
        user=actor,
        workspace=workspace,
    )
    return ActiveContextRead.from_resolved(targets=targets, resolved=resolved)
