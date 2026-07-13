"""HTTP-boundary coverage for PKCE OAuth connection creation."""

from importlib import import_module
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import jwt
import pytest
from httpx2 import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.audit_event import AuditEvent
from models.integrations import ExternalCredential, IntegrationConnection, IntegrationOAuthState
from services.integrations.oauth.fetch_external_principal import ExternalPrincipal
from services.integrations.oauth.utils import code_challenge

pytestmark = pytest.mark.asyncio


async def test_start_and_callback_are_pkce_bound_and_single_use(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = integration_identity["headers"]
    start = await db_async_client.post(
        "/api/v1/integrations/connections/oauth/start",
        headers=headers,
        json={
            "provider_key": "gmail",
            "owner_scope": "user",
            "label": "Client inbox",
            "next_path": "/integrations?provider=gmail",
        },
    )
    assert start.status_code == 200, start.text
    payload = start.json()
    query = parse_qs(urlparse(payload["authorization_url"]).query)
    assert query["client_id"] == ["gmail-integration-client"]
    assert query["include_granted_scopes"] == ["false"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"][0]
    connection = await db_session.get(IntegrationConnection, payload["connection_id"])
    assert connection is not None
    assert connection.status == "auth_pending"
    assert connection.label == "Client inbox"
    assert await db_session.scalar(select(func.count()).select_from(IntegrationOAuthState)) == 1

    module = import_module("services.integrations.connections.complete_oauth_callback")
    seen: dict[str, str] = {}

    async def exchange(*, provider_key: str, code: str, code_verifier: str):
        assert code_challenge(code_verifier) == query["code_challenge"][0]
        seen["verifier"] = code_verifier
        return {
            "access_token": "access-secret",
            "refresh_token": "refresh-secret",
            "expires_in": 3600,
            "scope": (
                "https://www.googleapis.com/auth/gmail.readonly "
                "https://www.googleapis.com/auth/userinfo.email"
            ),
        }

    async def principal(*, provider_key: str, access_token: str):
        assert access_token == "access-secret"
        return ExternalPrincipal("principal-1", "owner@example.com")

    monkeypatch.setattr(module, "exchange_authorization_code", exchange)
    monkeypatch.setattr(module, "fetch_external_principal", principal)
    callback = await db_async_client.post(
        "/api/v1/integrations/oauth/callback",
        headers=headers,
        json={"state": payload["state"], "code": "authorization-code"},
    )
    assert callback.status_code == 200, callback.text
    assert callback.json()["next_path"] == "/integrations?provider=gmail"
    assert callback.json()["connection"]["id"] == payload["connection_id"]
    assert callback.json()["connection"]["status"] == "active"
    assert seen["verifier"]

    db_session.expire_all()
    connection = await db_session.get(IntegrationConnection, payload["connection_id"])
    assert connection is not None and connection.status == "active"
    credential = await db_session.get(ExternalCredential, connection.credential_id)
    assert credential is not None
    assert credential.access_token_encrypted != "access-secret"
    assert credential.refresh_token_encrypted != "refresh-secret"
    assert credential.granted_scopes == ["https://www.googleapis.com/auth/gmail.readonly"]

    replay = await db_async_client.post(
        "/api/v1/integrations/oauth/callback",
        headers=headers,
        json={"state": payload["state"], "code": "authorization-code"},
    )
    assert replay.status_code == 401
    assert replay.json()["operation"] == "oauth_state"


async def test_duplicate_principal_is_reported_but_not_blocked(
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = import_module("services.integrations.connections.complete_oauth_callback")

    async def exchange(*, provider_key: str, code: str, code_verifier: str):
        return {
            "access_token": f"access-{code}",
            "refresh_token": f"refresh-{code}",
            "scope": "https://www.googleapis.com/auth/gmail.readonly",
        }

    async def principal(*, provider_key: str, access_token: str):
        return ExternalPrincipal("shared-principal", "shared@example.com")

    monkeypatch.setattr(module, "exchange_authorization_code", exchange)
    monkeypatch.setattr(module, "fetch_external_principal", principal)
    connection_ids: list[str] = []
    for label in ("Primary inbox", "Secondary inbox"):
        started = await db_async_client.post(
            "/api/v1/integrations/connections/oauth/start",
            headers=integration_identity["headers"],
            json={"provider_key": "gmail", "owner_scope": "user", "label": label},
        )
        assert started.status_code == 200
        payload = started.json()
        connection_ids.append(payload["connection_id"])
        callback = await db_async_client.post(
            "/api/v1/integrations/oauth/callback",
            headers=integration_identity["headers"],
            json={"state": payload["state"], "code": label},
        )
        assert callback.status_code == 200

    detail = await db_async_client.get(
        f"/api/v1/integrations/connections/{connection_ids[1]}",
        headers=integration_identity["headers"],
    )
    assert detail.status_code == 200
    assert detail.json()["duplicate_of_connection_ids"] == [connection_ids[0]]


async def test_signed_state_for_different_owner_is_rejected_without_consuming_it(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    started = await db_async_client.post(
        "/api/v1/integrations/connections/oauth/start",
        headers=integration_identity["headers"],
        json={"provider_key": "gmail", "owner_scope": "user", "label": "Bound owner"},
    )
    assert started.status_code == 200
    payload = started.json()
    claims = jwt.decode(payload["state"], options={"verify_signature": False})
    claims["user_id"] = str(uuid4())
    mismatched_state = jwt.encode(
        claims,
        settings.SECRET_KEY.get_secret_value(),
        algorithm="HS256",
    )

    callback = await db_async_client.post(
        "/api/v1/integrations/oauth/callback",
        headers=integration_identity["headers"],
        json={"state": mismatched_state, "code": "authorization-code"},
    )
    assert callback.status_code == 401
    assert callback.json()["operation"] == "oauth_state"
    db_session.expire_all()
    connection = await db_session.get(IntegrationConnection, payload["connection_id"])
    assert connection is not None and connection.status == "auth_pending"
    assert await db_session.scalar(select(func.count()).select_from(IntegrationOAuthState)) == 1


async def test_cancelled_callback_is_audited_and_can_be_restarted(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
) -> None:
    started = await db_async_client.post(
        "/api/v1/integrations/connections/oauth/start",
        headers=integration_identity["headers"],
        json={"provider_key": "gmail", "owner_scope": "user", "label": "Retry me"},
    )
    assert started.status_code == 200
    payload = started.json()

    cancelled = await db_async_client.post(
        "/api/v1/integrations/oauth/callback",
        headers=integration_identity["headers"],
        json={"state": payload["state"], "error": "access_denied"},
    )
    assert cancelled.status_code == 401
    assert cancelled.json()["operation"] == "oauth_callback"
    db_session.expire_all()
    connection = await db_session.get(IntegrationConnection, payload["connection_id"])
    assert connection is not None and connection.status == "needs_reauth"
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.resource_id == payload["connection_id"],
                AuditEvent.status == "failure",
            )
        )
        == 1
    )

    restarted = await db_async_client.post(
        "/api/v1/integrations/connections/oauth/start",
        headers=integration_identity["headers"],
        json={
            "provider_key": "gmail",
            "owner_scope": "user",
            "label": "Retry me",
            "connection_id": payload["connection_id"],
        },
    )
    assert restarted.status_code == 200, restarted.text
    assert restarted.json()["connection_id"] == payload["connection_id"]
    assert await db_session.scalar(select(func.count()).select_from(IntegrationOAuthState)) == 1


async def test_unexpected_provider_failure_redirects_and_allows_reauthentication(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = await db_async_client.post(
        "/api/v1/integrations/connections/oauth/start",
        headers=integration_identity["headers"],
        json={"provider_key": "gmail", "owner_scope": "user", "label": "Malformed"},
    )
    assert started.status_code == 200
    payload = started.json()
    module = import_module("services.integrations.connections.complete_oauth_callback")

    async def malformed_exchange(**kwargs):
        raise ValueError("malformed provider response")

    monkeypatch.setattr(module, "exchange_authorization_code", malformed_exchange)
    callback = await db_async_client.post(
        "/api/v1/integrations/oauth/callback",
        headers=integration_identity["headers"],
        json={"state": payload["state"], "code": "authorization-code"},
    )

    assert callback.status_code == 400
    assert callback.json()["operation"] == "complete_oauth_callback"
    db_session.expire_all()
    connection = await db_session.get(IntegrationConnection, payload["connection_id"])
    assert connection is not None and connection.status == "needs_reauth"
