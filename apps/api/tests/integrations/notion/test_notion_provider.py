"""Notion OAuth, identity, client, and discovery contracts."""

import base64
import json
from collections.abc import Iterator
from traceback import format_exception
from urllib.parse import parse_qs, urlparse

import httpx2
import pytest
from pydantic import SecretStr

from core.exceptions.integration import IntegrationAuthError
from core.settings import settings
from integrations.notion import PROVIDER
from integrations.notion.client import NOTION_API_VERSION
from integrations.notion.identity import extract_token_identity, fetch_token_identity
from integrations.notion.settings import notion_settings
from services.integrations import http as integration_http
from services.integrations.oauth import (
    build_authorization_url,
    exchange_authorization_code,
    refresh_authorization_token,
    revoke_authorization_token,
)
from services.integrations.plugin import PROVIDER_PLUGINS

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
    [
        "access_token",
    ],
)
def test_token_identity_rejects_each_missing_required_field(missing_field: str) -> None:
    payload = _token_payload()
    payload.pop(missing_field)

    with pytest.raises(IntegrationAuthError, match="identity response was rejected"):
        extract_token_identity(payload)


@pytest.mark.parametrize(
    "owner_type",
    [
        "workspace",
    ],
)
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


def test_identity_error_text_does_not_expose_provider_values() -> None:
    secret_value = "provider-token-secret"
    payload = _token_payload()
    payload["access_token"] = secret_value
    payload["owner"] = {"type": "workspace", "workspace": {"id": secret_value}}

    with pytest.raises(IntegrationAuthError) as exc_info:
        extract_token_identity(payload)

    assert secret_value not in "".join(format_exception(exc_info.value))
