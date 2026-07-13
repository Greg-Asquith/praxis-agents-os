# apps/api/routes/integrations/list_connections.py

"""List visible integration connections."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_read
from services.integrations.connections import list_connections as list_connections_service
from services.integrations.connections.schemas import ConnectionListResponse

router = APIRouter(dependencies=[Depends(require_read)])


@router.get("/connections")
async def list_connections(
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ConnectionListResponse:
    workspace, membership = workspace_context
    return await list_connections_service(
        db,
        actor=actor,
        workspace=workspace,
        membership=membership,
        limit=limit,
        offset=offset,
    )
