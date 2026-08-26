"""Connection read, rename, and revoke lifecycle tests."""

from dataclasses import replace
from datetime import timedelta
from importlib import import_module
from types import SimpleNamespace

import pytest
from httpx2 import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationAuthError
from models.audit_event import AuditEvent
from models.integrations import ExternalCredential, IntegrationConnection
from models.jobs import Job
from services.integrations.credentials import store_oauth_credential
from services.integrations.oauth import ExternalPrincipal
from services.integrations.plugin import PROVIDER_PLUGINS
from tests.factories import build_integration_discovery_run

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


async def test_revocation_protocol_can_require_the_access_token(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = await _oauth_connection(db_session, integration_identity)
    connection_id = connection.id
    module = import_module("services.integrations.connections.revoke_connection")
    gmail_plugin = PROVIDER_PLUGINS["gmail"]
    assert gmail_plugin.oauth_config is not None
    gmail_config = gmail_plugin.oauth_config()
    access_only_config = replace(
        gmail_config,
        protocol=replace(gmail_config.protocol, revoke_token="access"),  # noqa: S106
    )
    monkeypatch.setitem(
        PROVIDER_PLUGINS,
        "gmail",
        replace(gmail_plugin, oauth_config=lambda: access_only_config),
    )
    revoked_tokens: list[str] = []

    async def revoke_authorization_token(*, provider_key: str, token: str) -> None:
        assert provider_key == "gmail"
        revoked_tokens.append(token)

    monkeypatch.setattr(module, "revoke_authorization_token", revoke_authorization_token)
    response = await db_async_client.post(
        f"/api/v1/integrations/connections/{connection_id}/revoke",
        headers=integration_identity["headers"],
    )

    assert response.status_code == 200, response.text
    assert revoked_tokens == ["access-value"]


async def test_revocation_crypto_shreds_when_provider_config_is_unavailable(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = await _oauth_connection(db_session, integration_identity)
    connection_id = connection.id
    module = import_module("services.integrations.connections.revoke_connection")

    def unavailable_config(_provider_key: str):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        module,
        "resolve_provider_oauth_config",
        unavailable_config,
    )
    response = await db_async_client.post(
        f"/api/v1/integrations/connections/{connection_id}/revoke",
        headers=integration_identity["headers"],
    )

    assert response.status_code == 200, response.text
    db_session.expire_all()
    persisted = await db_session.get(IntegrationConnection, connection_id)
    assert persisted is not None
    credential = await db_session.get(ExternalCredential, persisted.credential_id)
    assert credential is not None
    assert credential.access_token_encrypted is None
    assert credential.refresh_token_encrypted is None
    assert credential.revoked_at is not None


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


async def test_connection_list_includes_latest_discovery_run(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    connection = await _oauth_connection(db_session, integration_identity)
    earlier_run = build_integration_discovery_run(
        connection=connection,
        resources_found=1,
    )
    latest_run = build_integration_discovery_run(
        connection=connection,
        resources_found=3,
        started_at=earlier_run.started_at + timedelta(seconds=1),
    )
    expected_started_at = latest_run.started_at.isoformat().replace("+00:00", "Z")
    expected_finished_at = latest_run.finished_at.isoformat().replace("+00:00", "Z")
    db_session.add_all([earlier_run, latest_run])
    await db_session.commit()
    response = await db_async_client.get(
        "/api/v1/integrations/connections",
        headers=integration_identity["headers"],
    )
    assert response.status_code == 200
    assert response.json()["items"][0]["latest_discovery_run"] == {
        "status": "succeeded",
        "resources_found": 3,
        "error_code": None,
        "started_at": expected_started_at,
        "finished_at": expected_finished_at,
    }
    assert response.json()["items"][0]["discovery_in_flight"] is False


async def test_connection_list_reports_whether_pending_discovery_has_work(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    connection = await _oauth_connection(db_session, integration_identity)
    connection.status = "discovery_pending"
    job = Job(
        kind="integrations.discover_resources",
        workspace_id=connection.owner_workspace_id,
        subject_type="integration_connection",
        subject_id=connection.id,
        content_hash="connection-list-discovery",
        payload={},
    )
    db_session.add(job)
    await db_session.commit()

    response = await db_async_client.get(
        "/api/v1/integrations/connections",
        headers=integration_identity["headers"],
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["discovery_in_flight"] is True


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

    async def resolve_external_principal(*, provider_key: str, access_token: str):
        assert provider_key == "gmail"
        assert access_token == "refreshed-access"
        return ExternalPrincipal("principal-lifecycle", "refreshed@example.com")

    monkeypatch.setattr(
        refresh_utils_module,
        "refresh_authorization_token",
        refresh_authorization_token,
    )
    monkeypatch.setattr(test_module, "resolve_external_principal", resolve_external_principal)
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


async def test_connection_test_keeps_stored_label_when_live_identity_omits_it(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = await _oauth_connection(db_session, integration_identity)
    module = import_module("services.integrations.connections.test_connection")

    async def resolve_external_principal(
        *, provider_key: str, access_token: str
    ) -> ExternalPrincipal:
        assert provider_key == "gmail"
        assert access_token == "access-value"
        return ExternalPrincipal("principal-lifecycle", None)

    monkeypatch.setattr(
        module,
        "resolve_external_principal",
        resolve_external_principal,
    )
    response = await db_async_client.post(
        f"/api/v1/integrations/connections/{connection.id}/test",
        headers=integration_identity["headers"],
    )

    assert response.status_code == 200, response.text
    assert response.json()["external_principal_label"] == "owner@example.com"


async def test_connection_test_forces_refresh_after_identity_auth_rejection(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = await _oauth_connection(db_session, integration_identity)
    module = import_module("services.integrations.connections.test_connection")
    refresh_calls: list[bool] = []

    async def ensure_fresh_credential(*args, force: bool = False, **kwargs):
        refresh_calls.append(force)
        return SimpleNamespace(
            access_token="fresh-access" if force else "stale-access",
            provider_key="gmail",
        )

    async def resolve_external_principal(
        *, provider_key: str, access_token: str
    ) -> ExternalPrincipal:
        assert provider_key == "gmail"
        if access_token == "stale-access":
            raise IntegrationAuthError(
                "Access token rejected",
                provider_key=provider_key,
                operation="oauth_userinfo",
            )
        assert access_token == "fresh-access"
        return ExternalPrincipal("principal-lifecycle", "refreshed@example.com")

    monkeypatch.setattr(module, "ensure_fresh_credential", ensure_fresh_credential)
    monkeypatch.setattr(module, "resolve_external_principal", resolve_external_principal)

    response = await db_async_client.post(
        f"/api/v1/integrations/connections/{connection.id}/test",
        headers=integration_identity["headers"],
    )

    assert response.status_code == 200, response.text
    assert response.json()["external_principal_label"] == "refreshed@example.com"
    assert refresh_calls == [False, True]


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

    monkeypatch.setattr(module, "resolve_external_principal", rejected_identity)
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
