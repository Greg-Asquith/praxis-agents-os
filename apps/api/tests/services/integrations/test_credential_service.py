"""Credential encryption, deduplication, refresh failure, and crypto-shred tests."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx2
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, update

from core.database import set_session_tenant_context
from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationNotFoundError,
    IntegrationRateLimitError,
    IntegrationValidationError,
)
from integrations.gmail import PROVIDER as GMAIL_PROVIDER
from models.audit_event import AuditEvent
from models.integrations import ExternalCredential, IntegrationConnection
from models.notification import Notification
from models.user import User
from models.workspace import Workspace
from services.integrations.connections.utils import refresh_oauth_credential
from services.integrations.credentials import (
    ensure_fresh_credential,
    find_duplicate_principals,
    get_usable_connection_credential,
    revoke_credential,
    store_oauth_credential,
    store_secret_reference_credential,
)
from services.integrations.microsoft_graph import classify_entra_token_error
from services.integrations.plugin import PROVIDER_PLUGINS, OAuthClientConfig, OAuthProtocol
from services.secrets.domain import SecretReference
from tests.factories import build_user, build_workspace

pytestmark = pytest.mark.asyncio


async def _connection(db_session, credential, *, status="active") -> IntegrationConnection:
    user = build_user(email=f"credential-{uuid4()}@example.com")
    workspace = await db_session.get(Workspace, credential.owner_workspace_id)
    assert workspace is not None
    db_session.add(user)
    await db_session.flush()
    await set_session_tenant_context(
        db_session,
        workspace_id=workspace.id,
        user_id=user.id,
    )
    connection = IntegrationConnection(
        provider_key=credential.provider_key,
        label="Credential test",
        owner_workspace_id=workspace.id,
        credential_id=credential.id,
        connected_by_user_id=user.id,
        status=status,
    )
    db_session.add(connection)
    await db_session.flush()
    return connection


async def _stored(
    db_session,
    *,
    principal="principal-1",
    expires_in=3600,
    owner_workspace_id=None,
    provider_key="test_provider",
):
    if owner_workspace_id is None:
        workspace = build_workspace(slug=f"credential-owner-{uuid4()}")
        db_session.add(workspace)
        await db_session.flush()
        owner_workspace_id = workspace.id
    await set_session_tenant_context(db_session, workspace_id=owner_workspace_id)
    return await store_oauth_credential(
        db_session,
        provider_key=provider_key,
        token_payload={
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
            "expires_in": expires_in,
            "token_type": "Bearer",
        },
        external_principal_id=principal,
        external_principal_label="principal@example.com",
        granted_scopes=["read"],
        owner_workspace_id=owner_workspace_id,
    )


async def test_oauth_tokens_are_ciphertext_at_rest_and_key_id_is_stamped(db_session) -> None:
    credential = await _stored(db_session)
    assert credential.access_token == "access-secret"
    assert credential.refresh_token == "refresh-secret"
    assert credential.access_token_encrypted != "access-secret"
    assert credential.refresh_token_encrypted != "refresh-secret"
    assert len(credential.encryption_key_id) == 16


async def test_secret_reference_store_rejects_oauth_mode_before_database_write(
    db_session,
) -> None:
    with pytest.raises(IntegrationValidationError):
        await store_secret_reference_credential(
            db_session,
            provider_key="test_provider",
            auth_mode="oauth",
            secret_reference=SecretReference(
                provider="local",
                name="integrations/test/credential",
                version="latest",
            ),
        )


async def test_duplicate_principal_detection_warns_without_blocking(db_session) -> None:
    first = await _stored(db_session, principal="same-principal")
    second = await _stored(
        db_session,
        principal="same-principal",
        owner_workspace_id=first.owner_workspace_id,
    )
    cross_workspace = await _stored(db_session, principal="same-principal")
    first_connection = await _connection(db_session, first)
    second_connection = await _connection(db_session, second)
    cross_workspace_connection = await _connection(db_session, cross_workspace)
    await set_session_tenant_context(
        db_session,
        workspace_id=first_connection.owner_workspace_id,
    )
    duplicates = await find_duplicate_principals(
        db_session,
        provider_key="test_provider",
        principal_fingerprint=first.principal_fingerprint,
        owner_user_id=None,
        owner_workspace_id=first_connection.owner_workspace_id,
        exclude_credential_id=first.id,
    )
    assert duplicates == [second_connection.id]
    assert cross_workspace_connection.id not in duplicates
    assert first_connection.id != second_connection.id


async def test_refresh_failure_sets_needs_reauth_and_notifies_once(db_session) -> None:
    credential = await _stored(db_session, expires_in=1)
    credential.token_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    connection = await _connection(db_session, credential)
    with pytest.raises(IntegrationAuthError):
        await ensure_fresh_credential(db_session, credential_id=credential.id)
    await db_session.refresh(credential)
    await db_session.refresh(connection)
    assert credential.refresh_failure_count == 1
    assert connection.status == "needs_reauth"
    notification = await db_session.scalar(
        select(Notification).where(
            Notification.notification_type == "integration_needs_reauth",
            Notification.recipient_user_id == connection.connected_by_user_id,
        )
    )
    assert notification is not None
    failure_events = await db_session.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.resource_id == str(credential.id), AuditEvent.status == "failure")
    )
    assert failure_events == 1


async def test_transient_refresh_failure_preserves_connection_and_error_type(db_session) -> None:
    credential = await _stored(db_session, expires_in=1)
    credential.token_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    connection = await _connection(db_session, credential)

    async def rate_limited(_credential):
        raise IntegrationRateLimitError(
            "Provider rate limited refresh",
            provider_key="test_provider",
            operation="refresh_credential",
        )

    with pytest.raises(IntegrationRateLimitError):
        await ensure_fresh_credential(
            db_session,
            credential_id=credential.id,
            refresh_token=rate_limited,
        )
    await db_session.refresh(credential)
    await db_session.refresh(connection)
    assert credential.access_token == "access-secret"
    assert credential.refresh_token == "refresh-secret"
    assert credential.refresh_failure_count == 1
    assert credential.last_refresh_error_code == "IntegrationRateLimitError"
    assert connection.status == "active"


async def test_terminal_refresh_rejection_requires_reauthentication(db_session) -> None:
    credential = await _stored(db_session, expires_in=1)
    credential.token_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    connection = await _connection(db_session, credential)

    async def invalid_grant(_credential):
        raise IntegrationValidationError(
            "Provider rejected the refresh grant",
            provider_key="test_provider",
            operation="refresh_credential",
        )

    with pytest.raises(IntegrationValidationError):
        await ensure_fresh_credential(
            db_session,
            credential_id=credential.id,
            refresh_token=invalid_grant,
        )
    await db_session.refresh(credential)
    await db_session.refresh(connection)
    assert credential.refresh_failure_count == 1
    assert connection.status == "needs_reauth"


async def test_classified_refresh_failure_persists_recovery_reason(db_session) -> None:
    credential = await _stored(db_session, expires_in=1)
    credential.token_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    connection = await _connection(db_session, credential)

    async def invalid_grant(_credential):
        raise IntegrationAuthError(
            "Provider rejected the refresh grant",
            provider_key="test_provider",
            operation="refresh_credential",
            error_code="reauthorization_required",
        )

    with pytest.raises(IntegrationAuthError):
        await ensure_fresh_credential(
            db_session,
            credential_id=credential.id,
            refresh_token=invalid_grant,
        )
    await db_session.refresh(credential)
    await db_session.refresh(connection)
    assert credential.last_refresh_error_code == "reauthorization_required"
    assert connection.status == "needs_reauth"
    assert connection.status_reason == "reauthorization_required"


@pytest.mark.parametrize(
    ("entra_code", "expected_reason"),
    [
        (700082, "reauthorization_required"),
        (7000215, "client_credential_invalid"),
    ],
)
async def test_entra_400_refresh_failure_persists_classified_reason(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    entra_code: int,
    expected_reason: str,
) -> None:
    from services.integrations import http as http_module

    config = OAuthClientConfig(
        client_id="client-id",
        client_secret=SecretStr("client-secret"),
        authorization_url="https://login.microsoftonline.com/tenant/oauth2/v2.0/authorize",
        token_url="https://login.microsoftonline.com/tenant/oauth2/v2.0/token",  # noqa: S106
        revoke_url="",
        protocol=OAuthProtocol(classify_token_error=classify_entra_token_error),
    )
    monkeypatch.setitem(
        PROVIDER_PLUGINS,
        "gmail",
        replace(GMAIL_PROVIDER, oauth_config=lambda: config),
    )
    async_client_type = httpx2.AsyncClient

    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            400,
            headers={"Content-Type": "application/json"},
            json={
                "error": "invalid_grant",
                "error_description": f"AADSTS{entra_code}: token request rejected",
                "error_codes": [entra_code],
            },
        )

    monkeypatch.setattr(
        http_module.httpx2,
        "AsyncClient",
        lambda: async_client_type(transport=httpx2.MockTransport(handler)),
    )
    credential = await _stored(db_session, expires_in=1, provider_key="gmail")
    credential.token_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    connection = await _connection(db_session, credential)

    with pytest.raises(IntegrationAuthError) as exc_info:
        await ensure_fresh_credential(
            db_session,
            credential_id=credential.id,
            refresh_token=refresh_oauth_credential,
        )
    await db_session.refresh(credential)
    await db_session.refresh(connection)
    assert exc_info.value.error_code == expected_reason
    assert credential.last_refresh_error_code == expected_reason
    assert connection.status == "needs_reauth"
    assert connection.status_reason == expected_reason
    if expected_reason == "client_credential_invalid":
        assert "OAuth client credential is invalid or expired" in caplog.text


async def test_unexpected_refresh_failure_does_not_mark_reauthentication(db_session) -> None:
    credential = await _stored(db_session, expires_in=1)
    credential.token_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    connection = await _connection(db_session, credential)

    async def programming_failure(_credential):
        raise RuntimeError("refresh callback bug")

    with pytest.raises(RuntimeError, match="callback bug"):
        await ensure_fresh_credential(
            db_session,
            credential_id=credential.id,
            refresh_token=programming_failure,
        )
    await db_session.refresh(credential)
    await db_session.refresh(connection)
    assert credential.refresh_failure_count == 0
    assert credential.last_refresh_error_code is None
    assert connection.status == "active"


async def test_revoked_credential_is_rejected_by_freshness_seam(db_session) -> None:
    credential = await _stored(db_session)
    await _connection(db_session, credential)
    await revoke_credential(db_session, credential_id=credential.id)

    with pytest.raises(IntegrationAuthError, match="revoked"):
        await ensure_fresh_credential(db_session, credential_id=credential.id)


async def test_freshness_seam_rejects_a_mismatched_expected_binding(db_session) -> None:
    credential = await _stored(db_session)

    with pytest.raises(IntegrationNotFoundError):
        await ensure_fresh_credential(
            db_session,
            credential_id=credential.id,
            expected_provider_key=credential.provider_key,
            expected_owner=(None, uuid4()),
        )


@pytest.mark.parametrize("revoked_state", ["connection", "credential"])
async def test_provider_credential_use_refreshes_and_rejects_in_flight_revocation(
    db_session,
    revoked_state: str,
) -> None:
    credential = await _stored(db_session)
    connection = await _connection(db_session, credential)
    actor = await db_session.get(User, connection.connected_by_user_id)
    workspace = await db_session.get(Workspace, connection.owner_workspace_id)
    assert actor is not None and workspace is not None
    assert (
        await get_usable_connection_credential(
            db_session,
            connection_id=connection.id,
            actor=actor,
            workspace=workspace,
        )
    ).id == credential.id

    if revoked_state == "connection":
        statement = (
            update(IntegrationConnection)
            .where(IntegrationConnection.id == connection.id)
            .values(status="revoked")
        )
    else:
        statement = (
            update(ExternalCredential)
            .where(ExternalCredential.id == credential.id)
            .values(revoked_at=datetime.now(UTC))
        )
    await db_session.execute(statement.execution_options(synchronize_session=False))

    # Simulate the prepared runtime retaining pre-revocation ORM objects.
    assert connection.status == "active"
    assert credential.revoked_at is None
    with pytest.raises(IntegrationAuthError, match="not available"):
        await get_usable_connection_credential(
            db_session,
            connection_id=connection.id,
            actor=actor,
            workspace=workspace,
        )


async def test_revoke_crypto_shreds_and_audit_contains_no_tokens(db_session) -> None:
    credential = await _stored(db_session)
    connection = await _connection(db_session, credential)
    await revoke_credential(db_session, credential_id=credential.id)
    assert credential.access_token_encrypted is None
    assert credential.refresh_token_encrypted is None
    assert credential.encryption_key_id is None
    assert credential.revoked_at is not None
    assert connection.status == "revoked"
    events = list(
        (
            await db_session.scalars(
                select(AuditEvent).where(AuditEvent.resource_id == str(credential.id))
            )
        ).all()
    )
    rendered = repr([event.details for event in events])
    assert "access-secret" not in rendered
    assert "refresh-secret" not in rendered
