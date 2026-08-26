"""Notion OAuth, identity, client, and discovery contracts."""

import base64
import json
from collections.abc import Iterator
from importlib import import_module
from traceback import format_exception
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx2
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.integration import IntegrationAuthError, IntegrationValidationError
from core.settings import settings
from integrations.notion import PROVIDER
from integrations.notion.client import NOTION_API_VERSION, NotionClient
from integrations.notion.discover_resources import discover_resources
from integrations.notion.identity import extract_token_identity, fetch_token_identity
from integrations.notion.settings import notion_settings
from models.integrations import IntegrationResource
from services.integrations import http as integration_http
from services.integrations.discovery.run_discovery import run_discovery
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.loader import _validate_plugin
from services.integrations.manifest import PROVIDER_MANIFESTS
from services.integrations.oauth import (
    build_authorization_url,
    exchange_authorization_code,
    refresh_authorization_token,
    revoke_authorization_token,
)
from services.integrations.plugin import PROVIDER_PLUGINS
from tests.factories import (
    build_external_credential,
    build_integration_connection,
    build_user,
    build_workspace,
)

ACCESS_TOKEN = "notion-access-token"
REFRESH_TOKEN = "notion-refresh-token"


@pytest.fixture
def notion_oauth(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    original_plugins = dict(PROVIDER_PLUGINS)
    PROVIDER_PLUGINS["notion"] = PROVIDER
    monkeypatch.setattr(notion_settings, "NOTION_OAUTH_CLIENT_ID", "notion-client")
    monkeypatch.setattr(
        notion_settings,
        "NOTION_OAUTH_CLIENT_SECRET",
        SecretStr("notion-secret"),
    )
    monkeypatch.setattr(
        settings,
        "INTEGRATIONS_OAUTH_REDIRECT_URI",
        "https://app.example.test/integrations/oauth/callback",
    )
    yield
    PROVIDER_PLUGINS.clear()
    PROVIDER_PLUGINS.update(original_plugins)


def _token_payload() -> dict[str, object]:
    return {
        "access_token": ACCESS_TOKEN,
        "refresh_token": REFRESH_TOKEN,
        "workspace_id": "workspace-1",
        "workspace_name": "Example workspace",
        "bot_id": "bot-1",
        "owner": {"type": "user", "user": {"id": "user-1"}},
    }


def _user_payload() -> dict[str, object]:
    return {
        "id": "bot-1",
        "type": "bot",
        "bot": {
            "workspace_id": "workspace-1",
            "workspace_name": None,
            "owner": {"type": "user", "user": {"id": "user-1"}},
        },
    }


def _install_transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    original_client = httpx2.AsyncClient
    monkeypatch.setattr(
        integration_http.httpx2,
        "AsyncClient",
        lambda: original_client(transport=httpx2.MockTransport(handler)),
    )


def test_authorization_url_contains_only_notion_parameters(notion_oauth: None) -> None:
    url = build_authorization_url(
        PROVIDER.manifest,
        state="signed-state",
        code_verifier="stored-only",
    )

    assert url.startswith("https://api.notion.com/v1/oauth/authorize?")
    assert parse_qs(urlparse(url).query) == {
        "client_id": ["notion-client"],
        "redirect_uri": ["https://app.example.test/integrations/oauth/callback"],
        "response_type": ["code"],
        "owner": ["user"],
        "state": ["signed-state"],
    }


async def test_token_exchange_refresh_and_revoke_use_basic_json(
    notion_oauth: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if request.url.path.endswith("/oauth/revoke"):
            return httpx2.Response(200, json={}, request=request)
        return httpx2.Response(200, json=_token_payload(), request=request)

    _install_transport(monkeypatch, handler)
    exchanged = await exchange_authorization_code(
        provider_key="notion",
        code="authorization-code",
        code_verifier="stored-only",
    )
    refreshed = await refresh_authorization_token(
        provider_key="notion",
        refresh_token=REFRESH_TOKEN,
    )
    await revoke_authorization_token(provider_key="notion", token=ACCESS_TOKEN)

    expected_auth = "Basic " + base64.b64encode(b"notion-client:notion-secret").decode()
    assert exchanged["access_token"] == ACCESS_TOKEN
    assert refreshed["refresh_token"] == REFRESH_TOKEN
    assert [request.headers["Notion-Version"] for request in requests] == [
        NOTION_API_VERSION,
        NOTION_API_VERSION,
        NOTION_API_VERSION,
    ]
    assert [request.headers["Authorization"] for request in requests] == [expected_auth] * 3
    assert json.loads(requests[0].content) == {
        "code": "authorization-code",
        "redirect_uri": "https://app.example.test/integrations/oauth/callback",
        "grant_type": "authorization_code",
    }
    assert json.loads(requests[1].content) == {
        "refresh_token": REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }
    assert json.loads(requests[2].content) == {"token": ACCESS_TOKEN}
    assert all(b"client_secret" not in request.content for request in requests)


def test_token_identity_retains_only_bounded_non_secret_metadata() -> None:
    payload = _token_payload()
    payload["workspace_name"] = "W" * 300

    principal = extract_token_identity(payload)

    assert principal.external_id == "workspace-1:user-1"
    assert principal.label == "W" * 255
    assert principal.connection_metadata == {
        "workspace_id": "workspace-1",
        "workspace_name": "W" * 255,
        "bot_id": "bot-1",
        "owner_user_id": "user-1",
        "api_version": NOTION_API_VERSION,
    }
    assert not {"access_token", "refresh_token", "token"}.intersection(
        principal.connection_metadata
    )


@pytest.mark.parametrize(
    "missing_field",
    ["access_token", "refresh_token", "workspace_id", "bot_id"],
)
def test_token_identity_rejects_each_missing_required_field(missing_field: str) -> None:
    payload = _token_payload()
    payload.pop(missing_field)

    with pytest.raises(IntegrationAuthError, match="identity response was rejected"):
        extract_token_identity(payload)


@pytest.mark.parametrize("owner_type", ["workspace", None])
def test_token_identity_rejects_non_user_owners(owner_type: object) -> None:
    payload = _token_payload()
    payload["owner"] = {"type": owner_type, "user": {"id": "user-1"}}

    with pytest.raises(IntegrationAuthError, match="identity response was rejected"):
        extract_token_identity(payload)


async def test_live_identity_matches_token_identity_for_the_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/users/me"
        assert request.headers["Authorization"] == f"Bearer {ACCESS_TOKEN}"
        assert request.headers["Notion-Version"] == NOTION_API_VERSION
        return httpx2.Response(200, json=_user_payload(), request=request)

    _install_transport(monkeypatch, handler)
    extracted = extract_token_identity(_token_payload())
    fetched = await fetch_token_identity(ACCESS_TOKEN)

    assert fetched.external_id == extracted.external_id
    assert fetched.label is None
    assert fetched.connection_metadata == {
        "workspace_id": "workspace-1",
        "bot_id": "bot-1",
        "owner_user_id": "user-1",
        "api_version": NOTION_API_VERSION,
    }


async def test_discovery_returns_one_stable_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=_user_payload(), request=request)

    _install_transport(monkeypatch, handler)
    first = await discover_resources(ACCESS_TOKEN, "Example workspace")
    second = await discover_resources(ACCESS_TOKEN, "Example workspace")

    assert first == second
    assert len(first) == 1
    assert first[0].resource_type == "notion_workspace"
    assert first[0].external_id == "workspace-1"
    assert first[0].display_name == "Example workspace"
    assert first[0].writable is True
    assert first[0].required_write_scopes == ()
    assert first[0].permissions_metadata == {"bot_id": "bot-1"}


async def test_discovery_rejects_a_response_without_a_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _user_payload()
    payload["bot"].pop("workspace_id")

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=payload, request=request)

    _install_transport(monkeypatch, handler)
    with pytest.raises(IntegrationValidationError, match="invalid response"):
        await discover_resources(ACCESS_TOKEN)


async def test_discovery_reconciles_the_same_resource_across_two_runs(
    db_session: AsyncSession,
    notion_oauth: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_manifests = dict(PROVIDER_MANIFESTS)
    PROVIDER_MANIFESTS["notion"] = PROVIDER.manifest
    unique_id = uuid4().hex
    user = build_user(email=f"notion-{unique_id}@example.com")
    workspace = build_workspace(slug=f"notion-{unique_id}")
    credential = build_external_credential(
        provider_key="notion",
        auth_mode="oauth",
        access_token_encrypted="ciphertext",  # noqa: S106 - inert encrypted test value
        external_principal_label="Example workspace",
    )
    db_session.add_all([user, workspace, credential])
    await db_session.flush()
    connection = build_integration_connection(
        provider_key="notion",
        credential=credential,
        user=user,
        workspace=workspace,
        status="discovery_pending",
    )
    db_session.add(connection)
    await db_session.flush()

    async def fresh_credential(*args, **kwargs):
        return SimpleNamespace(
            access_token=ACCESS_TOKEN,
            granted_scopes=[],
            external_principal_label="Example workspace",
        )

    discovery_module = import_module("services.integrations.discovery.run_discovery")
    monkeypatch.setattr(discovery_module, "ensure_fresh_credential", fresh_credential)

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=_user_payload(), request=request)

    _install_transport(monkeypatch, handler)
    try:
        first = await run_discovery(db_session, connection_id=connection.id)
        resource = await db_session.scalar(
            select(IntegrationResource).where(IntegrationResource.connection_id == connection.id)
        )
        second = await run_discovery(db_session, connection_id=connection.id)

        assert resource is not None
        assert first.resources_added == 1
        assert second.resources_added == 0
        assert second.resources_unchanged == 1
        assert resource.external_id == "workspace-1"
        assert resource.permissions_metadata == {"bot_id": "bot-1"}
    finally:
        PROVIDER_MANIFESTS.clear()
        PROVIDER_MANIFESTS.update(original_manifests)


async def test_client_refreshes_once_after_auth_rejection() -> None:
    forces: list[bool] = []
    requests = 0

    async def token(force: bool) -> str:
        forces.append(force)
        return "fresh" if force else "stale"

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal requests
        requests += 1
        expected = "stale" if requests == 1 else "fresh"
        assert request.headers["Authorization"] == f"Bearer {expected}"
        return httpx2.Response(401 if requests == 1 else 200, json=_user_payload(), request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http_client:
        payload = await NotionClient(token, client=http_client).get(
            "users/me",
            operation="oauth_identity",
            policy=IntegrationRequestPolicy.READ,
        )

    assert payload == _user_payload()
    assert forces == [False, True]


async def test_fixed_token_stops_before_retrying_the_same_rejected_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal requests
        requests += 1
        return httpx2.Response(401, json={}, request=request)

    _install_transport(monkeypatch, handler)

    with pytest.raises(IntegrationAuthError, match="requires refresh"):
        await fetch_token_identity(ACCESS_TOKEN)

    assert requests == 1


def test_provider_contract_is_valid() -> None:
    config = _validate_plugin(PROVIDER, expected_key="notion")

    assert config is not None
    assert PROVIDER.manifest.owner_scope == "user"
    assert PROVIDER.manifest.oauth_scopes == ()
    assert config.protocol.request_headers == (("Notion-Version", NOTION_API_VERSION),)


def test_identity_error_text_does_not_expose_provider_values() -> None:
    secret_value = "provider-token-secret"
    payload = _token_payload()
    payload["access_token"] = secret_value
    payload["owner"] = {"type": "workspace", "workspace": {"id": secret_value}}

    with pytest.raises(IntegrationAuthError) as exc_info:
        extract_token_identity(payload)

    assert secret_value not in "".join(format_exception(exc_info.value))
