# apps/api/routes/integrations/list_connection_resources.py

"""List discovered resources for one integration connection."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_read
from services.integrations.connections import (
    list_connection_resources as list_connection_resources_service,
)
from services.integrations.connections.schemas import IntegrationResourceRead

router = APIRouter(dependencies=[Depends(require_read)])


@router.get("/connections/{connection_id}/resources")
async def list_connection_resources(
    connection_id: Annotated[UUID, Path()],
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> list[IntegrationResourceRead]:
    workspace, _membership = workspace_context
    return await list_connection_resources_service(
        db,
        connection_id=connection_id,
        actor=actor,
        workspace=workspace,
    )
