"""Credential encryption, deduplication, refresh failure, and crypto-shred tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationRateLimitError,
    IntegrationValidationError,
)
from models.audit_event import AuditEvent
from models.integrations import IntegrationConnection
from models.notification import Notification
from services.integrations.credentials import (
    ensure_fresh_credential,
    find_duplicate_principals,
    revoke_credential,
    store_oauth_credential,
    store_secret_reference_credential,
)
from services.secrets.domain import SecretReference
from tests.factories import build_user, build_workspace

pytestmark = pytest.mark.asyncio


async def _connection(db_session, credential, *, status="active") -> IntegrationConnection:
    user = build_user(email=f"credential-{uuid4()}@example.com")
    workspace = build_workspace(slug=f"credential-{uuid4()}")
    db_session.add_all([user, workspace])
    await db_session.flush()
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


async def _stored(db_session, *, principal="principal-1", expires_in=3600):
    return await store_oauth_credential(
        db_session,
        provider_key="test_provider",
        token_payload={
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
            "expires_in": expires_in,
            "token_type": "Bearer",
        },
        external_principal_id=principal,
        external_principal_label="principal@example.com",
        granted_scopes=["read"],
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
    second = await _stored(db_session, principal="same-principal")
    first_connection = await _connection(db_session, first)
    second_connection = await _connection(db_session, second)
    duplicates = await find_duplicate_principals(
        db_session,
        provider_key="test_provider",
        principal_fingerprint=first.principal_fingerprint,
        exclude_credential_id=first.id,
    )
    assert duplicates == [second_connection.id]
    assert first_connection.id != second_connection.id


async def test_refresh_failure_sets_needs_reauth_without_notification(db_session) -> None:
    credential = await _stored(db_session, expires_in=1)
    credential.token_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    connection = await _connection(db_session, credential)
    with pytest.raises(IntegrationAuthError):
        await ensure_fresh_credential(db_session, credential_id=credential.id)
    await db_session.refresh(credential)
    await db_session.refresh(connection)
    assert credential.refresh_failure_count == 1
    assert connection.status == "needs_reauth"
    assert await db_session.scalar(select(func.count()).select_from(Notification)) == 0
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
