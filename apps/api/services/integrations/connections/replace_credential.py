# apps/api/services/integrations/connections/replace_credential.py

"""Replace a non-OAuth credential without replacing its connection."""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import (
    IntegrationConnectionError,
    IntegrationValidationError,
)
from models.integrations import ExternalCredential, IntegrationConnection
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditResourceType
from services.integrations.connections.schemas import (
    ConnectionRead,
    CredentialReplacementRequest,
)
from services.integrations.connections.utils import (
    connection_to_read,
    get_visible_connection,
    require_connection_mutation_allowed,
)
from services.integrations.credentials import parse_google_service_account_json
from services.integrations.discovery import enqueue_discovery
from services.integrations.utils import (
    compute_principal_fingerprint,
    ensure_credential_keys_loaded,
    record_integration_audit,
)
from services.secrets import resolve_secret, write_secret
from services.secrets.domain import SecretReference
from services.secrets.factory import get_secrets_provider

logger = logging.getLogger(__name__)


async def replace_credential(
    db: AsyncSession,
    *,
    connection_id: UUID,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    payload: CredentialReplacementRequest,
) -> ConnectionRead:
    visible = await get_visible_connection(
        db,
        connection_id=connection_id,
        actor=actor,
        workspace=workspace,
    )
    require_connection_mutation_allowed(visible, actor=actor, membership=membership)
    current_credential = await db.get(ExternalCredential, visible.credential_id)
    _validate_replaceable(visible, current_credential)
    if current_credential is None:  # narrowed by _validate_replaceable
        raise AssertionError("Credential validation must reject missing credentials")

    created_reference = False
    replacement_reference: SecretReference
    service_account_email: str | None = None
    principal_id: str
    principal_label: str | None = None
    try:
        if payload.secret_reference is not None:
            replacement_reference = SecretReference(
                provider=payload.secret_reference.provider,
                name=payload.secret_reference.name,
                version=payload.secret_reference.version,
            )
            raw_value = await resolve_secret(
                db,
                replacement_reference,
                workspace_id=workspace.id,
                actor_id=actor.id,
            )
            if current_credential.auth_mode == "service_account":
                parsed = parse_google_service_account_json(
                    raw_value,
                    provider_key=visible.provider_key,
                )
                service_account_email = parsed.client_email
        else:
            raw_value = _raw_replacement_value(current_credential.auth_mode, payload)
            if current_credential.auth_mode == "service_account":
                parsed = parse_google_service_account_json(
                    raw_value,
                    provider_key=visible.provider_key,
                )
                service_account_email = parsed.client_email
            replacement_reference = await write_secret(
                db,
                name=current_credential.secret_name or "",
                value=raw_value,
                workspace_id=workspace.id,
                actor_id=actor.id,
            )
            created_reference = True

        if current_credential.auth_mode == "service_account":
            if service_account_email is None:
                raise AssertionError("Service-account validation must produce an email")
            principal_id = service_account_email
            principal_label = service_account_email
        else:
            principal_id = replacement_reference.name

        connection, credential = await _lock_current_rows(
            db,
            connection_id=visible.id,
            expected_credential_id=current_credential.id,
            expected_auth_mode=current_credential.auth_mode,
        )
        await ensure_credential_keys_loaded(db)
        credential.secret_provider = replacement_reference.provider
        credential.secret_name = replacement_reference.name
        credential.secret_version = replacement_reference.version
        credential.principal_fingerprint = compute_principal_fingerprint(
            connection.provider_key,
            principal_id,
        )
        credential.external_principal_label = principal_label
        if credential.auth_mode == "service_account":
            connection.provider_metadata = {
                **(connection.provider_metadata or {}),
                "service_account_email": principal_label,
            }
        await record_integration_audit(
            db,
            workspace_id=workspace.id,
            action=AuditAction.UPDATE,
            resource_type=AuditResourceType.INTEGRATION_CREDENTIAL,
            resource_id=credential.id,
            details={
                "provider_key": connection.provider_key,
                "auth_mode": credential.auth_mode,
                "reference": replacement_reference.render(),
                "principal_fingerprint": credential.principal_fingerprint,
            },
        )
        await enqueue_discovery(db, connection=connection)
        await db.flush()
        return await connection_to_read(db, connection, include_credential=True)
    except Exception:
        if created_reference and replacement_reference.provider == "local":
            try:
                await get_secrets_provider().delete_secret(replacement_reference)
            except Exception:
                logger.warning(
                    "Failed to clean up an unreferenced local credential version",
                    exc_info=True,
                )
        raise


def _validate_replaceable(
    connection: IntegrationConnection,
    credential: ExternalCredential | None,
) -> None:
    if connection.status == "revoked":
        raise IntegrationConnectionError(
            "Revoked connections cannot replace credentials",
            provider_key=connection.provider_key,
            connection_id=str(connection.id),
            operation="replace_credential",
        )
    if credential is None or credential.deleted or credential.revoked_at is not None:
        raise IntegrationConnectionError(
            "Connection credential is missing or revoked",
            provider_key=connection.provider_key,
            connection_id=str(connection.id),
            operation="replace_credential",
        )
    if credential.auth_mode == "oauth":
        raise IntegrationValidationError(
            "OAuth connections must use the sign-in flow",
            provider_key=connection.provider_key,
            connection_id=str(connection.id),
            operation="replace_credential",
        )
    if credential.auth_mode == "system_token":
        raise IntegrationValidationError(
            "System-token credentials cannot be replaced by users",
            provider_key=connection.provider_key,
            connection_id=str(connection.id),
            operation="replace_credential",
        )


def _raw_replacement_value(
    auth_mode: str,
    payload: CredentialReplacementRequest,
) -> str:
    if auth_mode == "api_key" and payload.api_key is not None:
        return payload.api_key.get_secret_value()
    if auth_mode == "service_account" and payload.service_account_json is not None:
        return payload.service_account_json.get_secret_value()
    expected = "api_key" if auth_mode == "api_key" else "service_account_json"
    raise IntegrationValidationError(
        f"Credential replacement for this connection requires {expected}",
        operation="replace_credential",
    )


async def _lock_current_rows(
    db: AsyncSession,
    *,
    connection_id: UUID,
    expected_credential_id: UUID,
    expected_auth_mode: str,
) -> tuple[IntegrationConnection, ExternalCredential]:
    connection = await db.scalar(
        select(IntegrationConnection)
        .where(
            IntegrationConnection.id == connection_id,
            IntegrationConnection.credential_id == expected_credential_id,
            IntegrationConnection.deleted.is_(False),
        )
        .with_for_update()
    )
    credential = await db.scalar(
        select(ExternalCredential)
        .where(
            ExternalCredential.id == expected_credential_id,
            ExternalCredential.auth_mode == expected_auth_mode,
            ExternalCredential.deleted.is_(False),
            ExternalCredential.revoked_at.is_(None),
        )
        .with_for_update()
    )
    if connection is None or credential is None:
        raise IntegrationConnectionError(
            "Connection changed while its credential was being prepared",
            connection_id=str(connection_id),
            operation="replace_credential",
        )
    _validate_replaceable(connection, credential)
    return connection, credential
