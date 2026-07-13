# apps/api/routes/integrations/refresh_connection.py

"""Refresh an integration connection credential."""

from uuid import UUID

from fastapi import APIRouter, Depends

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_editor
from services.integrations.connections import refresh_connection as refresh_connection_service
from services.integrations.connections.schemas import ConnectionRefreshResponse

router = APIRouter(dependencies=[Depends(require_editor)])


@router.post("/connections/{connection_id}/refresh")
async def refresh_connection(
    connection_id: UUID,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> ConnectionRefreshResponse:
    workspace, membership = workspace_context
    return await refresh_connection_service(
        db,
        connection_id=connection_id,
        actor=actor,
        workspace=workspace,
        membership=membership,
    )
