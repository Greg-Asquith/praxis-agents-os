# apps/api/services/integrations/credentials/utils.py

"""Private helpers shared by integration credential operations."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.database import SESSION_USER_ID_KEY, SESSION_WORKSPACE_ID_KEY
from core.exceptions.integration import IntegrationError
from models.integrations import ExternalCredential, IntegrationConnection
from services.audit_events import AuditAction, AuditResourceType, AuditStatus
from services.integrations.connections.transition_connection_status import (
    transition_connection_status,
)
from services.integrations.domain import CONNECTION_STATUS_NEEDS_REAUTH
from services.integrations.utils import record_integration_audit


def resolve_credential_owner(
    db: AsyncSession,
    *,
    provider_key: str,
    owner_user_id: UUID | None,
    owner_workspace_id: UUID | None,
) -> tuple[UUID | None, UUID | None]:
    """Resolve the immutable credential owner from explicit or session context."""
    if (owner_user_id is None) == (owner_workspace_id is None):
        if owner_user_id is not None:
            raise ValueError("Credential ownership must select exactly one owner")
        from services.integrations.manifest import PROVIDER_MANIFESTS

        manifest = PROVIDER_MANIFESTS.get(provider_key)
        if manifest is not None and manifest.owner_scope == "user":
            owner_user_id = db.info.get(SESSION_USER_ID_KEY)
        else:
            owner_workspace_id = db.info.get(SESSION_WORKSPACE_ID_KEY)
    if (owner_user_id is None) == (owner_workspace_id is None):
        raise ValueError("Credential ownership is unavailable from the runtime session")
    return owner_user_id, owner_workspace_id


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
