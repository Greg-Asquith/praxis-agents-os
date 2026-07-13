# apps/api/routes/integrations/revoke_connection.py

"""Revoke an integration connection."""

from uuid import UUID

from fastapi import APIRouter, Depends

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_editor
from services.integrations.connections import revoke_connection as revoke_connection_service
from services.integrations.connections.schemas import ConnectionRead

router = APIRouter(dependencies=[Depends(require_editor)])


@router.post("/connections/{connection_id}/revoke")
async def revoke_connection(
    connection_id: UUID,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> ConnectionRead:
    workspace, membership = workspace_context
    return await revoke_connection_service(
        db,
        connection_id=connection_id,
        actor=actor,
        workspace=workspace,
        membership=membership,
    )
