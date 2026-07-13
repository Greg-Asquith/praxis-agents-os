# apps/api/services/integrations/connections/refresh_connection.py

"""Force-refresh one OAuth integration connection."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationConnectionError
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.integrations.connections.schemas import ConnectionRefreshResponse
from services.integrations.connections.utils import (
    get_visible_connection,
    refresh_oauth_credential,
    require_connection_mutation_allowed,
)
from services.integrations.credentials import ensure_fresh_credential
from services.integrations.utils import record_integration_audit


async def refresh_connection(
    db: AsyncSession,
    *,
    connection_id: UUID,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
) -> ConnectionRefreshResponse:
    connection = await get_visible_connection(
        db,
        connection_id=connection_id,
        actor=actor,
        workspace=workspace,
    )
    require_connection_mutation_allowed(connection, actor=actor, membership=membership)
    if connection.status == "revoked":
        raise IntegrationConnectionError(
            "Revoked connections cannot be refreshed",
            provider_key=connection.provider_key,
            connection_id=str(connection.id),
            operation="refresh_connection",
        )

    credential = await ensure_fresh_credential(
        db,
        credential_id=connection.credential_id,
        refresh_token=refresh_oauth_credential,
        force=True,
    )
    await record_integration_audit(
        db,
        workspace_id=workspace.id,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.INTEGRATION_CONNECTION,
        resource_id=connection.id,
        details={"refreshed": True},
    )
    return ConnectionRefreshResponse(
        connection_id=connection.id,
        status=connection.status,
        token_expires_at=credential.token_expires_at,
    )
