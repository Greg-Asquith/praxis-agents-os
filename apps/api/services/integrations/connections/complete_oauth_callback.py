# apps/api/services/integrations/connections/complete_oauth_callback.py

"""Consume one OAuth callback and replace its pending credential atomically."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import configure_async_db_session, get_async_db_session_factory
from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationConnectionError,
    IntegrationError,
)
from models.integrations import ExternalCredential, IntegrationConnection, IntegrationOAuthState
from models.user import User
from models.workspace import Workspace
from services.audit_events import AuditAction, AuditResourceType, AuditStatus
from services.integrations.connections.schemas import OAuthCallbackResponse
from services.integrations.connections.transition_connection_status import (
    transition_connection_status,
)
from services.integrations.connections.utils import connection_to_read
from services.integrations.credentials import store_oauth_credential
from services.integrations.domain import (
    CONNECTION_STATUS_ACTIVE,
    CONNECTION_STATUS_AUTH_PENDING,
    CONNECTION_STATUS_DISCOVERY_PENDING,
)
from services.integrations.manifest import PROVIDER_MANIFESTS
from services.integrations.oauth import exchange_authorization_code, fetch_external_principal
from services.integrations.oauth.utils import (
    decrypt_code_verifier,
    verify_integration_oauth_state,
)
from services.integrations.utils import record_integration_audit
from services.security import SecurityEventType, safe_record_security_event_committed


async def complete_oauth_callback(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    code: str | None,
    state: str,
    provider_error: str | None,
    ip_address: str,
    endpoint: str,
) -> OAuthCallbackResponse:
    try:
        claims = verify_integration_oauth_state(state)
    except IntegrationAuthError:
        await _record_invalid_state(ip_address=ip_address, endpoint=endpoint)
        raise

    if str(claims["user_id"]) != str(actor.id) or str(claims["workspace_id"]) != str(workspace.id):
        await _record_invalid_state(ip_address=ip_address, endpoint=endpoint)
        raise IntegrationAuthError(
            "Integration OAuth state does not match the authenticated context",
            operation="oauth_state",
        )

    jti = str(claims["jti"])
    encrypted_verifier = await _consume_pending_state(jti)
    if encrypted_verifier is None:
        await _record_invalid_state(ip_address=ip_address, endpoint=endpoint, jti=jti)
        raise IntegrationAuthError("Integration OAuth state is invalid", operation="oauth_state")

    connection_id = UUID(str(claims["connection_id"]))
    audit_workspace_id = UUID(str(claims["workspace_id"]))
    connection = await db.scalar(
        select(IntegrationConnection).where(
            IntegrationConnection.id == connection_id,
            IntegrationConnection.deleted.is_(False),
        )
    )
    if connection is None or connection.status != CONNECTION_STATUS_AUTH_PENDING:
        if connection is not None:
            await _record_callback_failure(
                db,
                connection,
                error_code="connection_not_pending",
                superseded=True,
                audit_workspace_id=audit_workspace_id,
            )
        raise IntegrationConnectionError(
            "OAuth connection is not awaiting authorization",
            provider_key=str(claims["provider_key"]),
            connection_id=str(connection_id),
            operation="complete_oauth_callback",
        )
    if not _state_matches_connection(connection, claims):
        await _record_invalid_state(ip_address=ip_address, endpoint=endpoint, jti=jti)
        raise IntegrationAuthError(
            "Integration OAuth state does not match the connection",
            operation="oauth_state",
        )

    expected_credential_id = connection.credential_id
    manifest = PROVIDER_MANIFESTS.get(connection.provider_key)
    if manifest is None:
        await _mark_callback_failed(
            db,
            connection_id=connection_id,
            expected_credential_id=expected_credential_id,
            provider_key=connection.provider_key,
            error_code="provider_disabled",
            audit_workspace_id=audit_workspace_id,
        )
        raise IntegrationConnectionError(
            "Integration provider is no longer enabled",
            provider_key=connection.provider_key,
            connection_id=str(connection.id),
            operation="complete_oauth_callback",
        )
    try:
        if provider_error or not code:
            raise IntegrationAuthError(
                "Integration authorization was not completed",
                provider_key=connection.provider_key,
                operation="oauth_callback",
            )
        verifier = await decrypt_code_verifier(db, encrypted_verifier)
        token_payload = await exchange_authorization_code(
            provider_key=connection.provider_key,
            code=code,
            code_verifier=verifier,
        )
        access_token = str(token_payload["access_token"])
        principal = await fetch_external_principal(
            provider_key=connection.provider_key,
            access_token=access_token,
        )
        connection = await _lock_pending_connection(
            db,
            connection_id=connection_id,
            expected_credential_id=expected_credential_id,
            provider_key=connection.provider_key,
        )
    except IntegrationError as exc:
        await _mark_callback_failed(
            db,
            connection_id=connection_id,
            expected_credential_id=expected_credential_id,
            provider_key=connection.provider_key,
            error_code=type(exc).__name__,
            audit_workspace_id=audit_workspace_id,
        )
        raise
    except Exception as exc:
        wrapped = IntegrationConnectionError(
            "Integration provider returned an unexpected OAuth response",
            provider_key=connection.provider_key,
            connection_id=str(connection_id),
            operation="complete_oauth_callback",
            original_error=exc,
        )
        await _mark_callback_failed(
            db,
            connection_id=connection_id,
            expected_credential_id=expected_credential_id,
            provider_key=connection.provider_key,
            error_code=type(exc).__name__,
            audit_workspace_id=audit_workspace_id,
        )
        raise wrapped from exc

    granted = _filtered_scopes(token_payload.get("scope"), manifest.oauth_scopes)
    credential = await store_oauth_credential(
        db,
        provider_key=connection.provider_key,
        token_payload=token_payload,
        external_principal_id=principal.external_id,
        external_principal_label=principal.label,
        granted_scopes=granted,
    )
    previous_credential = await db.get(ExternalCredential, expected_credential_id)
    connection.credential_id = credential.id
    if previous_credential is not None:
        if previous_credential.principal_fingerprint.startswith("pending:"):
            await db.delete(previous_credential)
        else:
            previous_credential.crypto_shred()
            previous_credential.deleted = True
            previous_credential.deleted_at = datetime.now(UTC)
    target = (
        CONNECTION_STATUS_DISCOVERY_PENDING
        if manifest.requires_discovery
        else CONNECTION_STATUS_ACTIVE
    )
    # Resource discovery will enqueue here once its worker is available.
    await transition_connection_status(
        db,
        connection,
        target,
        reason="oauth_connected",
        audit_details={
            "granted_scopes": granted,
            "principal_fingerprint": credential.principal_fingerprint,
        },
        audit_workspace_id=audit_workspace_id,
    )
    await db.flush()
    return OAuthCallbackResponse(
        connection=await connection_to_read(db, connection, include_credential=True),
        next_path=claims.get("next_path"),
    )


async def _lock_pending_connection(
    db: AsyncSession,
    *,
    connection_id: UUID,
    expected_credential_id: UUID,
    provider_key: str,
) -> IntegrationConnection:
    connection = await db.scalar(
        select(IntegrationConnection)
        .where(
            IntegrationConnection.id == connection_id,
            IntegrationConnection.deleted.is_(False),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        connection is None
        or connection.status != CONNECTION_STATUS_AUTH_PENDING
        or connection.credential_id != expected_credential_id
    ):
        raise IntegrationConnectionError(
            "OAuth connection changed while authorization was completing",
            provider_key=provider_key,
            connection_id=str(connection_id),
            operation="complete_oauth_callback",
        )
    return connection


async def _mark_callback_failed(
    db: AsyncSession,
    *,
    connection_id: UUID,
    expected_credential_id: UUID,
    provider_key: str,
    error_code: str,
    audit_workspace_id: UUID,
) -> None:
    connection = await db.scalar(
        select(IntegrationConnection)
        .where(
            IntegrationConnection.id == connection_id,
            IntegrationConnection.deleted.is_(False),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if connection is None:
        return
    if (
        connection.status == CONNECTION_STATUS_AUTH_PENDING
        and connection.credential_id == expected_credential_id
    ):
        await transition_connection_status(
            db,
            connection,
            "needs_reauth",
            reason="oauth_callback_failed",
            audit_status=AuditStatus.FAILURE,
            audit_details={"provider_key": provider_key, "error_code": error_code},
            audit_workspace_id=audit_workspace_id,
        )
        return
    await _record_callback_failure(
        db,
        connection,
        error_code=error_code,
        superseded=True,
        audit_workspace_id=audit_workspace_id,
    )


async def _record_callback_failure(
    db: AsyncSession,
    connection: IntegrationConnection,
    *,
    error_code: str,
    superseded: bool,
    audit_workspace_id: UUID,
) -> None:
    await record_integration_audit(
        db,
        workspace_id=audit_workspace_id,
        action=AuditAction.UPDATE,
        resource_type=AuditResourceType.INTEGRATION_CONNECTION,
        resource_id=connection.id,
        status=AuditStatus.FAILURE,
        details={
            "provider_key": connection.provider_key,
            "error_code": error_code,
            "superseded": superseded,
        },
    )


async def _consume_pending_state(jti: str) -> str | None:
    """Consume state in its own committed transaction so provider failures cannot replay it."""
    session_factory = get_async_db_session_factory()
    async with session_factory() as consume_db:
        await configure_async_db_session(consume_db)
        value = await consume_db.scalar(
            delete(IntegrationOAuthState)
            .where(
                IntegrationOAuthState.jti == jti,
                IntegrationOAuthState.expires_at > datetime.now(UTC),
            )
            .returning(IntegrationOAuthState.code_verifier_encrypted)
        )
        await consume_db.commit()
        return value


async def _record_invalid_state(*, ip_address: str, endpoint: str, jti: str | None = None) -> None:
    await safe_record_security_event_committed(
        event_type=SecurityEventType.INTEGRATION_OAUTH_STATE_INVALID,
        ip_address=ip_address,
        endpoint=endpoint,
        details={"jti": jti} if jti else {},
    )


def _filtered_scopes(raw: object, requested: tuple[str, ...]) -> list[str]:
    if not isinstance(raw, str):
        return []
    granted = set(raw.split())
    return [scope for scope in requested if scope in granted]


def _state_matches_connection(
    connection: IntegrationConnection,
    claims: dict[str, object],
) -> bool:
    if connection.provider_key != claims["provider_key"]:
        return False
    if claims["owner_scope"] == "user":
        return connection.owner_user_id is not None and str(connection.owner_user_id) == str(
            claims["user_id"]
        )
    return connection.owner_workspace_id is not None and str(connection.owner_workspace_id) == str(
        claims["workspace_id"]
    )
