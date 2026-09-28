# apps/api/tests/routes/integrations/test_oauth_connect_flow.py

"""HTTP-boundary coverage for PKCE OAuth connection creation."""

from dataclasses import replace
from importlib import import_module
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import jwt
import pytest
from httpx2 import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.integrations import ExternalCredential, IntegrationConnection, IntegrationOAuthState
from models.jobs import Job
from services.integrations.manifest import PROVIDER_MANIFESTS
from services.integrations.oauth import ExternalPrincipal
from services.integrations.oauth.utils import code_challenge
from services.integrations.plugin import PROVIDER_PLUGINS, OAuthProtocol

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    "raw",
    [
        "https%3A%2F%2Fgraph.microsoft.com%2FMail.ReadWrite "
        "https%3A%2F%2Fgraph.microsoft.com%2Fmail.send openid",
    ],
)
async def test_callback_normalizes_resource_prefixed_scopes(raw: str) -> None:
    module = import_module("services.integrations.connections.complete_oauth_callback")
    protocol = OAuthProtocol(scope_resource_prefix="https://graph.microsoft.com/")
    assert module._filtered_scopes(
        raw,
        ("Mail.ReadWrite", "Mail.Send", "openid"),
        protocol,
    ) == ["Mail.ReadWrite", "Mail.Send", "openid"]


async def test_start_and_callback_are_pkce_bound_and_single_use(
    db_session: AsyncSession,
    db_async_client: AsyncClient,
    integration_identity: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discovery_calls = 0

    async def discover_resources(
        _credential: str,
        _principal_label: str | None = None,
        _pacing_key: str = "",
    ):
        nonlocal discovery_calls
        discovery_calls += 1
        return ()

    gmail_plugin = PROVIDER_PLUGINS["gmail"]
    discoverable_manifest = replace(
        gmail_plugin.manifest,
        resource_types=("gmail_mailbox",),
        requires_discovery=True,
    )
    PROVIDER_MANIFESTS["gmail"] = discoverable_manifest
    PROVIDER_PLUGINS["gmail"] = replace(
        gmail_plugin,
        manifest=discoverable_manifest,
        discover_resources=discover_resources,
    )
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
    connection.provider_metadata = {"preserved": "value"}
    await db_session.commit()
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

    async def principal(*, provider_key: str, access_token: str, token_payload: object):
        assert access_token == "access-secret"
        assert isinstance(token_payload, dict)
        return ExternalPrincipal(
            "principal-1",
            "owner@example.com",
            {"workspace_id": "workspace-1", "api_version": "2026-03-11"},
        )

    monkeypatch.setattr(module, "exchange_authorization_code", exchange)
    monkeypatch.setattr(module, "resolve_external_principal", principal)
    callback = await db_async_client.post(
        "/api/v1/integrations/oauth/callback",
        headers=headers,
        json={"state": payload["state"], "code": "authorization-code"},
    )
    assert callback.status_code == 200, callback.text
    assert callback.json()["next_path"] == "/integrations?provider=gmail"
    assert callback.json()["connection"]["id"] == payload["connection_id"]
    assert callback.json()["connection"]["status"] == "discovery_pending"
    assert seen["verifier"]
    assert discovery_calls == 0
    pending_job = await db_session.scalar(
        select(Job).where(
            Job.kind == "integrations.discover_resources",
            Job.subject_id == connection.id,
        )
    )
    assert pending_job is not None
    assert pending_job.initiated_by_user_id is None

    db_session.expire_all()
    connection = await db_session.get(IntegrationConnection, payload["connection_id"])
    assert connection is not None and connection.status == "discovery_pending"
    assert connection.provider_metadata == {
        "preserved": "value",
        "workspace_id": "workspace-1",
        "api_version": "2026-03-11",
    }
    assert "provider_metadata" not in callback.json()["connection"]
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
