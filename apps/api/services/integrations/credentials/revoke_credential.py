# apps/api/services/integrations/credentials/revoke_credential.py

"""Crypto-shred a credential and terminally revoke its connection."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationNotFoundError
from models.integrations import ExternalCredential, IntegrationConnection
from services.audit_events import AuditAction, AuditResourceType
from services.integrations.connections.transition_connection_status import (
    transition_connection_status,
)
from services.integrations.domain import CONNECTION_STATUS_REVOKED
from services.integrations.utils import record_integration_audit


async def revoke_credential(
    db: AsyncSession,
    *,
    credential_id: UUID,
    connection_audit_action: AuditAction = AuditAction.UPDATE,
) -> ExternalCredential:
    credential = await db.scalar(
        select(ExternalCredential)
        .where(ExternalCredential.id == credential_id, ExternalCredential.deleted.is_(False))
        .with_for_update()
    )
    if credential is None:
        raise IntegrationNotFoundError(
            "Integration credential not found",
            operation="revoke_credential",
        )
    connection = await db.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.credential_id == credential.id,
            IntegrationConnection.deleted.is_(False),
        )
    )
    credential.crypto_shred()
    if connection is not None:
        await transition_connection_status(
            db,
            connection,
            CONNECTION_STATUS_REVOKED,
            reason="credential_revoked",
            audit_action=connection_audit_action,
        )
    await db.flush()
    await record_integration_audit(
        db,
        workspace_id=connection.owner_workspace_id if connection else None,
        action=AuditAction.DELETE,
        resource_type=AuditResourceType.INTEGRATION_CREDENTIAL,
        resource_id=credential.id,
        details={"provider_key": credential.provider_key, "crypto_shredded": True},
    )
    return credential
