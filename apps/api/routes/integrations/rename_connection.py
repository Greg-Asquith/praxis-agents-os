# apps/api/routes/integrations/rename_connection.py

"""Rename an integration connection."""

from uuid import UUID

from fastapi import APIRouter, Depends

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_editor
from services.integrations.connections import rename_connection as rename_connection_service
from services.integrations.connections.schemas import ConnectionRead, RenameConnectionRequest

router = APIRouter(dependencies=[Depends(require_editor)])


@router.patch("/connections/{connection_id}")
async def rename_connection(
    connection_id: UUID,
    payload: RenameConnectionRequest,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> ConnectionRead:
    workspace, membership = workspace_context
    return await rename_connection_service(
        db,
        connection_id=connection_id,
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=payload,
    )
