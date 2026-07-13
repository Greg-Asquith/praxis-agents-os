"""Connection read, rename, and revoke lifecycle tests."""

from importlib import import_module

import pytest
from httpx2 import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationAuthError
from models.audit_event import AuditEvent
from models.integrations import ExternalCredential, IntegrationConnection
from services.integrations.credentials import store_oauth_credential
from services.integrations.oauth.fetch_external_principal import ExternalPrincipal

pytestmark = pytest.mark.asyncio


async def _oauth_connection(db: AsyncSession, identity: dict[str, object]) -> IntegrationConnection:
    credential = await store_oauth_credential(
        db,
        provider_key="gmail",
        token_payload={
            "access_token": "access-value",
            "refresh_token": "refresh-value",
            "expires_in": 3600,
        },
        external_principal_id="principal-lifecycle",
        external_principal_label="owner@example.com",
        granted_scopes=["scope-a"],
    )
    connection = IntegrationConnection(
        provider_key="gmail",
        label="Before",
        owner_user_id=identity["user"].id,
        credential_id=credential.id,
        connected_by_user_id=identity["user"].id,
        status="active",
    )
    db.add(connection)
    await db.commit()
    return connection


async def test_rename_and_revoke_crypto_shreds_even_when_remote_fails(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = await _oauth_connection(db_session, integration_identity)
    connection_id = connection.id
    rename = await db_async_client.patch(
        f"/api/v1/integrations/connections/{connection_id}",
        headers=integration_identity["headers"],
        json={"label": "After"},
    )
    assert rename.status_code == 200
    assert rename.json()["label"] == "After"

    module = import_module("services.integrations.connections.revoke_connection")

    async def failed_revoke(**kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(module, "revoke_authorization_token", failed_revoke)
    revoke = await db_async_client.post(
        f"/api/v1/integrations/connections/{connection_id}/revoke",
        headers=integration_identity["headers"],
    )
    assert revoke.status_code == 200, revoke.text
    assert revoke.json()["status"] == "revoked"
    db_session.expire_all()
    persisted = await db_session.get(IntegrationConnection, connection_id)
    credential = await db_session.get(ExternalCredential, persisted.credential_id)
    assert credential.access_token_encrypted is None
    assert credential.refresh_token_encrypted is None
    assert credential.revoked_at is not None

    rejected = await db_async_client.post(
        f"/api/v1/integrations/connections/{connection_id}/test",
        headers=integration_identity["headers"],
    )
    assert rejected.status_code == 400


async def test_read_only_connection_list_omits_credential_values(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    await _oauth_connection(db_session, integration_identity)
    response = await db_async_client.get(
        "/api/v1/integrations/connections",
        headers=integration_identity["headers"],
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["limit"] == 50
    assert response.json()["offset"] == 0
    body = response.text
    assert "access-value" not in body
    assert "refresh-value" not in body


async def test_refresh_and_test_connection_happy_paths(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = await _oauth_connection(db_session, integration_identity)
    connection_id = connection.id
    refresh_utils_module = import_module("services.integrations.connections.utils")
    test_module = import_module("services.integrations.connections.test_connection")

    async def refresh_authorization_token(*, provider_key: str, refresh_token: str):
        assert provider_key == "gmail"
        assert refresh_token == "refresh-value"
        return {"access_token": "refreshed-access", "expires_in": 7200}

    async def fetch_external_principal(*, provider_key: str, access_token: str):
        assert provider_key == "gmail"
        assert access_token == "refreshed-access"
        return ExternalPrincipal("principal-lifecycle", "refreshed@example.com")

    monkeypatch.setattr(
        refresh_utils_module,
        "refresh_authorization_token",
        refresh_authorization_token,
    )
    monkeypatch.setattr(test_module, "fetch_external_principal", fetch_external_principal)
    refreshed = await db_async_client.post(
        f"/api/v1/integrations/connections/{connection_id}/refresh",
        headers=integration_identity["headers"],
    )
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["token_expires_at"] is not None

    tested = await db_async_client.post(
        f"/api/v1/integrations/connections/{connection_id}/test",
        headers=integration_identity["headers"],
    )
    assert tested.status_code == 200, tested.text
    assert tested.json()["external_principal_label"] == "refreshed@example.com"


async def test_identity_auth_failure_marks_connection_needs_reauth(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = await _oauth_connection(db_session, integration_identity)
    connection_id = connection.id
    module = import_module("services.integrations.connections.test_connection")

    async def rejected_identity(**kwargs):
        raise IntegrationAuthError(
            "Identity rejected",
            provider_key="gmail",
            operation="oauth_userinfo",
        )

    monkeypatch.setattr(module, "fetch_external_principal", rejected_identity)
    failed = await db_async_client.post(
        f"/api/v1/integrations/connections/{connection_id}/test",
        headers=integration_identity["headers"],
    )
    assert failed.status_code == 401
    # The durable independent-session transition is asserted with real
    # committed connections in test_refresh_locking.


async def test_refresh_auth_failure_and_guarded_reauth_uses_one_connection_audit(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = await _oauth_connection(db_session, integration_identity)
    connection_id = connection.id
    old_credential_id = connection.credential_id
    refresh_utils_module = import_module("services.integrations.connections.utils")

    async def rejected_refresh(*, provider_key: str, refresh_token: str):
        raise IntegrationAuthError(
            "Refresh rejected",
            provider_key=provider_key,
            operation="oauth_token_refresh",
        )

    monkeypatch.setattr(refresh_utils_module, "refresh_authorization_token", rejected_refresh)
    failed = await db_async_client.post(
        f"/api/v1/integrations/connections/{connection_id}/refresh",
        headers=integration_identity["headers"],
    )
    assert failed.status_code == 401
    db_session.expire_all()
    persisted = await db_session.get(IntegrationConnection, connection_id)
    assert persisted is not None
    # Durable refresh-failure transitions are covered with independent
    # committed sessions in test_refresh_locking. The route fixture rolls its
    # outer transaction back on the intentional 401, so seed the reauth state
    # explicitly for the route-level restart assertion.
    persisted.status = "needs_reauth"
    persisted.status_reason = "credential_refresh_failed"
    await db_session.commit()

    before = await db_session.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.resource_type == "integration_connection",
            AuditEvent.resource_id == str(connection_id),
        )
    )
    restarted = await db_async_client.post(
        "/api/v1/integrations/connections/oauth/start",
        headers=integration_identity["headers"],
        json={
            "provider_key": "gmail",
            "owner_scope": "user",
            "label": "Reauthorized inbox",
            "connection_id": str(connection_id),
        },
    )
    assert restarted.status_code == 200, restarted.text
    after = await db_session.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.resource_type == "integration_connection",
            AuditEvent.resource_id == str(connection_id),
        )
    )
    assert after == before + 1
    db_session.expire_all()
    persisted = await db_session.get(IntegrationConnection, connection_id)
    assert persisted is not None and persisted.status == "auth_pending"
    assert persisted.credential_id == old_credential_id

    cancelled = await db_async_client.post(
        "/api/v1/integrations/oauth/callback",
        headers=integration_identity["headers"],
        json={"state": restarted.json()["state"], "error": "access_denied"},
    )
    assert cancelled.status_code == 401
    db_session.expire_all()
    persisted = await db_session.get(IntegrationConnection, connection_id)
    previous_credential = await db_session.get(ExternalCredential, old_credential_id)
    assert persisted is not None and persisted.status == "needs_reauth"
    assert persisted.credential_id == old_credential_id
    assert previous_credential is not None
    assert previous_credential.access_token == "access-value"
