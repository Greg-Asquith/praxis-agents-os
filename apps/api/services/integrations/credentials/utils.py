"""Private helpers shared by integration credential operations."""

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationError
from models.integrations import ExternalCredential, IntegrationConnection
from services.audit_events import AuditAction, AuditResourceType, AuditStatus
from services.integrations.connections.transition_connection_status import (
    transition_connection_status,
)
from services.integrations.domain import CONNECTION_STATUS_NEEDS_REAUTH
from services.integrations.utils import record_integration_audit


async def record_refresh_failure(
    db: AsyncSession,
    credential: ExternalCredential,
    connection: IntegrationConnection | None,
    exc: IntegrationError,
    *,
    needs_reauth: bool,
) -> None:
    """Persist typed provider failures in the refresh-owned transaction."""
    credential.refresh_failure_count = (credential.refresh_failure_count or 0) + 1
    credential.last_refresh_error_code = type(exc).__name__[:64]
    if (
        needs_reauth
        and connection is not None
        and connection.status != CONNECTION_STATUS_NEEDS_REAUTH
    ):
        await transition_connection_status(
            db,
            connection,
            CONNECTION_STATUS_NEEDS_REAUTH,
            reason="credential_refresh_failed",
        )
    await db.flush()
    await record_integration_audit(
        db,
        workspace_id=connection.owner_workspace_id if connection else None,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.INTEGRATION_CREDENTIAL,
        resource_id=credential.id,
        status=AuditStatus.FAILURE,
        details={
            "provider_key": credential.provider_key,
            "error_code": credential.last_refresh_error_code,
        },
    )
