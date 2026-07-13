# apps/api/routes/integrations/connect_api_key.py

"""Connect an API-key integration."""

from fastapi import APIRouter, Depends

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_owner
from services.integrations.connections import connect_api_key as connect_api_key_service
from services.integrations.connections.schemas import ApiKeyConnectRequest, ConnectionRead

router = APIRouter(dependencies=[Depends(require_owner)])


@router.post("/connections/api-key")
async def connect_api_key(
    payload: ApiKeyConnectRequest,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> ConnectionRead:
    workspace, _membership = workspace_context
    return await connect_api_key_service(db, actor=actor, workspace=workspace, payload=payload)
