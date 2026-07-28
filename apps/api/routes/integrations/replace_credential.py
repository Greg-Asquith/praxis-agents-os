# apps/api/routes/integrations/replace_credential.py

"""Replace a non-OAuth integration credential."""

from uuid import UUID

from fastapi import APIRouter, Depends

from core.dependencies import AsyncDbSessionDep, CurrentUserDep, CurrentWorkspaceDep, require_owner
from services.integrations.connections import replace_credential as replace_credential_service
from services.integrations.connections.schemas import (
    ConnectionRead,
    CredentialReplacementRequest,
)

router = APIRouter(dependencies=[Depends(require_owner)])


@router.put("/connections/{connection_id}/credential")
async def replace_credential(
    connection_id: UUID,
    payload: CredentialReplacementRequest,
    db: AsyncDbSessionDep,
    actor: CurrentUserDep,
    workspace_context: CurrentWorkspaceDep,
) -> ConnectionRead:
    workspace, membership = workspace_context
    return await replace_credential_service(
        db,
        connection_id=connection_id,
        actor=actor,
        workspace=workspace,
        membership=membership,
        payload=payload,
    )
