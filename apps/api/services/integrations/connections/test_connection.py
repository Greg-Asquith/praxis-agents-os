# apps/api/services/integrations/connections/test_connection.py

"""Validate a connection with the provider's cheapest identity operation."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import configure_async_db_session, get_async_db_session_factory
from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationConnectionError,
    IntegrationPermissionError,
)
from models.integrations import ExternalCredential, IntegrationConnection
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType, AuditStatus
from services.integrations.connections.schemas import ConnectionTestResponse
from services.integrations.connections.transition_connection_status import (
    transition_connection_status,
)
from services.integrations.connections.utils import (
    get_visible_connection,
    refresh_oauth_credential,
    require_connection_mutation_allowed,
)
from services.integrations.credentials import ensure_fresh_credential
from services.integrations.oauth import fetch_external_principal
from services.integrations.utils import record_integration_audit
from services.secrets import resolve_secret
from services.secrets.domain import SecretReference


async def test_connection(
    db: AsyncSession,
    *,
    connection_id: UUID,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
) -> ConnectionTestResponse:
    connection = await get_visible_connection(
        db,
        connection_id=connection_id,
        actor=actor,
        workspace=workspace,
    )
    require_connection_mutation_allowed(connection, actor=actor, membership=membership)
    if connection.status == "revoked":
        raise IntegrationConnectionError(
            "Revoked connections cannot be tested",
            provider_key=connection.provider_key,
            connection_id=str(connection.id),
            operation="test_connection",
        )
    credential = await db.get(ExternalCredential, connection.credential_id)
    if credential is None:
        raise IntegrationConnectionError(
            "Connection credential is missing",
            provider_key=connection.provider_key,
            operation="test_connection",
        )
    principal_label = credential.external_principal_label
    if credential.auth_mode == "oauth":
        fresh = await ensure_fresh_credential(
            db,
            credential_id=credential.id,
            refresh_token=refresh_oauth_credential,
        )
        access_token = fresh.access_token
        if not access_token:
            raise IntegrationConnectionError(
                "Connection has no access token",
                provider_key=fresh.provider_key,
                operation="test_connection",
            )
        try:
            principal = await fetch_external_principal(
                provider_key=fresh.provider_key, access_token=access_token
            )
        except (IntegrationAuthError, IntegrationPermissionError):
            await _mark_identity_test_failed(
                connection_id=connection.id,
                expected_credential_id=credential.id,
                audit_workspace_id=workspace.id,
            )
            raise
        principal_label = principal.label
    else:
        await resolve_secret(
            db,
            SecretReference(
                provider=credential.secret_provider or "",
                name=credential.secret_name or "",
                version=credential.secret_version or "",
            ),
            workspace_id=workspace.id,
            actor_id=actor.id,
        )
    await record_integration_audit(
        db,
        workspace_id=workspace.id,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.INTEGRATION_CONNECTION,
        resource_id=connection.id,
        details={"tested": True},
    )
    return ConnectionTestResponse(
        connection_id=connection.id,
        status=connection.status,
        external_principal_label=principal_label,
    )


async def _mark_identity_test_failed(
    *,
    connection_id: UUID,
    expected_credential_id: UUID,
    audit_workspace_id: UUID,
) -> None:
    session_factory = get_async_db_session_factory()
    async with session_factory() as failure_db:
        await configure_async_db_session(failure_db)
        connection = await failure_db.scalar(
            select(IntegrationConnection)
            .where(
                IntegrationConnection.id == connection_id,
                IntegrationConnection.credential_id == expected_credential_id,
                IntegrationConnection.deleted.is_(False),
            )
            .with_for_update()
        )
        if connection is not None and connection.status != "needs_reauth":
            await transition_connection_status(
                failure_db,
                connection,
                "needs_reauth",
                reason="credential_identity_test_failed",
                audit_status=AuditStatus.FAILURE,
                audit_details={"error_code": "provider_identity_rejected"},
                audit_workspace_id=audit_workspace_id,
            )
        await failure_db.commit()
