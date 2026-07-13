# apps/api/routes/integrations/test_connection.py

"""Test an integration connection."""

from uuid import UUID

from fastapi import APIRouter, Depends

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_editor
from services.integrations.connections import test_connection as test_connection_service
from services.integrations.connections.schemas import ConnectionTestResponse

router = APIRouter(dependencies=[Depends(require_editor)])


@router.post("/connections/{connection_id}/test")
async def test_connection(
    connection_id: UUID,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> ConnectionTestResponse:
    workspace, membership = workspace_context
    return await test_connection_service(
        db,
        connection_id=connection_id,
        actor=actor,
        workspace=workspace,
        membership=membership,
    )
