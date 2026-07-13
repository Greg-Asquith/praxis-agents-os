# apps/api/routes/integrations/get_connection.py

"""Get one visible integration connection."""

from uuid import UUID

from fastapi import APIRouter, Depends

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_read
from services.integrations.connections import get_connection as get_connection_service
from services.integrations.connections.schemas import ConnectionRead

router = APIRouter(dependencies=[Depends(require_read)])


@router.get("/connections/{connection_id}")
async def get_connection(
    connection_id: UUID,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> ConnectionRead:
    workspace, membership = workspace_context
    return await get_connection_service(
        db,
        connection_id=connection_id,
        actor=actor,
        workspace=workspace,
        membership=membership,
    )
