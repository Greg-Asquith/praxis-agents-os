# apps/api/routes/integrations/connect_service_account.py

"""Connect a service-account integration."""

from fastapi import APIRouter, Depends

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_owner
from services.integrations.connections import (
    connect_service_account as connect_service_account_service,
)
from services.integrations.connections.schemas import ConnectionRead, ServiceAccountConnectRequest

router = APIRouter(dependencies=[Depends(require_owner)])


@router.post("/connections/service-account")
async def connect_service_account(
    payload: ServiceAccountConnectRequest,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> ConnectionRead:
    workspace, _membership = workspace_context
    return await connect_service_account_service(
        db, actor=actor, workspace=workspace, payload=payload
    )
