# apps/api/routes/integrations/update_resouce_selection.py

"""Replace enabled resources for one integration connection."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_editor
from services.integrations.connections import (
    update_resource_selection as update_resource_selection_service,
)
from services.integrations.connections.schemas import (
    ResourceSelectionRequest,
    ResourceSelectionResponse,
)

router = APIRouter(dependencies=[Depends(require_editor)])


@router.put("/connections/{connection_id}/resources/selection")
async def update_resource_selection(
    connection_id: Annotated[UUID, Path()],
    payload: ResourceSelectionRequest,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> ResourceSelectionResponse:
    workspace, membership = workspace_context
    return await update_resource_selection_service(
        db,
        connection_id=connection_id,
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=payload,
    )
