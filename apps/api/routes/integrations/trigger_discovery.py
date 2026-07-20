# apps/api/routes/integrations/trigger_discovery.py

"""Trigger asynchronous discovery for one integration connection."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, status

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_editor
from services.integrations.connections import trigger_discovery as trigger_discovery_service
from services.integrations.connections.schemas import DiscoveryTriggerResponse

router = APIRouter(dependencies=[Depends(require_editor)])


@router.post(
    "/connections/{connection_id}/discover",
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_discovery(
    connection_id: Annotated[UUID, Path()],
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> DiscoveryTriggerResponse:
    workspace, membership = workspace_context
    return await trigger_discovery_service(
        db,
        connection_id=connection_id,
        actor=actor,
        workspace=workspace,
        membership=membership,
    )
