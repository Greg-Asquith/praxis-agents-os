# apps/api/routes/integrations/get_context.py

"""Get one conversation's active integration context selection."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_read
from services.integrations.context import (
    get_active_context_selection,
    resolve_active_context_targets,
)
from services.integrations.context.schemas import ActiveContextRead, ActiveContextSelectionValue

router = APIRouter(dependencies=[Depends(require_read)])


@router.get("/conversations/{conversation_id}/context")
async def get_context(
    conversation_id: Annotated[UUID, Path()],
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> ActiveContextRead:
    workspace, _membership = workspace_context
    selections = await get_active_context_selection(
        db,
        actor=actor,
        workspace=workspace,
        conversation_id=conversation_id,
    )
    targets = [ActiveContextSelectionValue.from_selection(selection) for selection in selections]
    resolved = await resolve_active_context_targets(
        db,
        selections=targets,
        user=actor,
        workspace=workspace,
    )
    return ActiveContextRead.from_resolved(targets=targets, resolved=resolved)
