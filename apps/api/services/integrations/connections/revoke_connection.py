# apps/api/services/integrations/connections/revoke_connection.py

"""Best-effort remote revocation followed by guaranteed local crypto-shredding."""

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.integrations import ExternalCredential
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction
from services.integrations.connections.schemas import ConnectionRead
from services.integrations.connections.utils import (
    connection_to_read,
    get_visible_connection,
    require_connection_mutation_allowed,
)
from services.integrations.credentials import revoke_credential
from services.integrations.oauth import revoke_authorization_token

logger = logging.getLogger(__name__)


async def revoke_connection(
    db: AsyncSession,
    *,
    connection_id: UUID,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
) -> ConnectionRead:
    connection = await get_visible_connection(
        db,
        connection_id=connection_id,
        actor=actor,
        workspace=workspace,
    )
    require_connection_mutation_allowed(connection, actor=actor, membership=membership)
    credential = await db.get(ExternalCredential, connection.credential_id)
    if credential is not None and credential.auth_mode == "oauth":
        token = credential.refresh_token or credential.access_token
        if token:
            try:
                await revoke_authorization_token(
                    provider_key=credential.provider_key,
                    token=token,
                )
            except Exception:
                logger.warning(
                    "Remote integration token revocation failed for provider %s",
                    credential.provider_key,
                    exc_info=True,
                )
    await revoke_credential(
        db,
        credential_id=connection.credential_id,
        connection_audit_action=AuditAction.DELETE,
    )
    await db.refresh(connection)
    return await connection_to_read(db, connection, include_credential=False)
