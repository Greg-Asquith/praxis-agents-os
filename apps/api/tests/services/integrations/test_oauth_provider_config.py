"""Provider-owned OAuth credentials stay isolated across Google services."""

from base64 import b64encode
from collections.abc import Iterator
from dataclasses import replace
from importlib import import_module
from traceback import format_exception
from urllib.parse import parse_qs, urlencode, urlparse
from uuid import uuid4

import httpx2
import pytest
from pydantic import SecretStr

from core.exceptions.integration import IntegrationAuthError, IntegrationConnectionError
from core.settings import settings
from integrations.gmail import PROVIDER as GMAIL_PROVIDER
from integrations.gmail.settings import gmail_settings
from integrations.google_ads import PROVIDER as GOOGLE_ADS_PROVIDER
from integrations.google_ads.settings import google_ads_settings
from models.integrations import ExternalCredential
from services.integrations.connections.utils import refresh_oauth_credential
from services.integrations.loader import _validate_plugin
from services.integrations.oauth import (
    ExternalPrincipal,
    build_authorization_url,
    exchange_authorization_code,
    refresh_authorization_token,
    resolve_external_principal,
    revoke_authorization_token,
)
from services.integrations.oauth.utils import code_challenge
from services.integrations.plugin import PROVIDER_PLUGINS, OAuthClientConfig, OAuthProtocol


@pytest.fixture
def isolated_google_oauth_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    original_plugins = dict(PROVIDER_PLUGINS)
    PROVIDER_PLUGINS.update({"gmail": GMAIL_PROVIDER, "google_ads": GOOGLE_ADS_PROVIDER})
    monkeypatch.setattr(gmail_settings, "GMAIL_OAUTH_CLIENT_ID", "gmail-client")
    monkeypatch.setattr(gmail_settings, "GMAIL_OAUTH_CLIENT_SECRET", SecretStr("gmail-secret"))
    monkeypatch.setattr(google_ads_settings, "GOOGLE_ADS_OAUTH_CLIENT_ID", "ads-client")
    monkeypatch.setattr(
        google_ads_settings,
        "GOOGLE_ADS_OAUTH_CLIENT_SECRET",
        SecretStr("ads-secret"),
    )
    monkeypatch.setattr(
        settings,
        "INTEGRATIONS_OAUTH_REDIRECT_URI",
        "https://app.example.test/integrations/oauth/callback",
    )
    yield
    PROVIDER_PLUGINS.clear()
    PROVIDER_PLUGINS.update(original_plugins)


def test_authorization_urls_use_each_providers_client_id(
    isolated_google_oauth_settings: None,
) -> None:
    gmail_url = build_authorization_url(
        GMAIL_PROVIDER.manifest,
        state="gmail-state",
        code_verifier="gmail-verifier",
    )
    ads_url = build_authorization_url(
        GOOGLE_ADS_PROVIDER.manifest,
        state="ads-state",
        code_verifier="ads-verifier",
    )

    assert parse_qs(urlparse(gmail_url).query)["client_id"] == ["gmail-client"]
    assert parse_qs(urlparse(ads_url).query)["client_id"] == ["ads-client"]
    assert {"openid", "email"}.issubset(
        set(parse_qs(urlparse(gmail_url).query)["scope"][0].split())
    )
    assert {"openid", "email"}.issubset(set(parse_qs(urlparse(ads_url).query)["scope"][0].split()))


def test_google_authorization_url_keeps_its_wire_contract(
    isolated_google_oauth_settings: None,
) -> None:
    verifier = "gmail-verifier"
    expected_query = urlencode(
        {
            "client_id": "gmail-client",
            "redirect_uri": "https://app.example.test/integrations/oauth/callback",
            "response_type": "code",
            "scope": " ".join(GMAIL_PROVIDER.manifest.oauth_scopes),
            "state": "gmail-state",
            "code_challenge": code_challenge(verifier),
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "false",
        }
    )

    assert (
        build_authorization_url(
            GMAIL_PROVIDER.manifest,
            state="gmail-state",
            code_verifier=verifier,
        )
        == f"https://accounts.google.com/o/oauth2/v2/auth?{expected_query}"
    )


def test_google_providers_declare_the_default_identity_source() -> None:
    gmail_config = GMAIL_PROVIDER.oauth_config()
    ads_config = GOOGLE_ADS_PROVIDER.oauth_config()

    assert gmail_config.protocol == OAuthProtocol(identity_source="google_userinfo")
    assert ads_config.protocol == OAuthProtocol(identity_source="google_userinfo")


def test_google_identity_lookup_uses_the_oidc_userinfo_endpoint() -> None:
    module = import_module("services.integrations.oauth.resolve_external_principal")
    assert module.GOOGLE_USERINFO_URL == "https://openidconnect.googleapis.com/v1/userinfo"


async def test_token_exchange_uses_each_providers_client_secret(
    isolated_google_oauth_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = import_module("services.integrations.oauth.exchange_authorization_code")
    sent: list[dict[str, str]] = []

    class Response:
        def json(self) -> dict[str, str]:
            return {"access_token": "access-token"}

    async def request_with_retries(method: str, url: str, **kwargs):
        sent.append(kwargs["data"])
        return Response()

    monkeypatch.setattr(module, "request_with_retries", request_with_retries)
    await exchange_authorization_code(
        provider_key="gmail",
        code="gmail-code",
        code_verifier="gmail-verifier",
    )
    await exchange_authorization_code(
        provider_key="google_ads",
        code="ads-code",
        code_verifier="ads-verifier",
    )

    assert sent[0]["client_id"] == "gmail-client"
    assert sent[0]["client_secret"] == "gmail-secret"
    assert sent[1]["client_id"] == "ads-client"
    assert sent[1]["client_secret"] == "ads-secret"


async def test_google_token_requests_keep_their_wire_contract(
    isolated_google_oauth_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = import_module("services.integrations.oauth.exchange_authorization_code")
    sent: list[dict[str, object]] = []

    class Response:
        def json(self) -> dict[str, str]:
            return {"access_token": "access-token"}

    async def request_with_retries(method: str, url: str, **kwargs):
        sent.append({"method": method, "url": url, **kwargs})
        return Response()

    monkeypatch.setattr(module, "request_with_retries", request_with_retries)
    await exchange_authorization_code(
        provider_key="gmail",
        code="gmail-code",
        code_verifier="gmail-verifier",
    )
    await refresh_authorization_token(
        provider_key="gmail",
        refresh_token="gmail-refresh",  # noqa: S106
    )

    assert sent[0]["data"] == {
        "code": "gmail-code",
        "client_id": "gmail-client",
        "client_secret": "gmail-secret",
        "redirect_uri": "https://app.example.test/integrations/oauth/callback",
        "grant_type": "authorization_code",
        "code_verifier": "gmail-verifier",
    }
    assert "headers" not in sent[0]
    assert "json" not in sent[0]
    assert sent[1]["data"] == {
        "refresh_token": "gmail-refresh",
        "client_id": "gmail-client",
        "client_secret": "gmail-secret",
        "grant_type": "refresh_token",
    }
    assert "headers" not in sent[1]
    assert "json" not in sent[1]


async def test_provider_protocol_controls_basic_json_requests_and_identity(
    isolated_google_oauth_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchange_module = import_module("services.integrations.oauth.exchange_authorization_code")
    sent: list[dict[str, object]] = []
    fetched_tokens: list[str] = []

    def extract_identity(payload: dict[str, object]) -> ExternalPrincipal:
        assert payload["workspace_id"] == "workspace-1"
        return ExternalPrincipal("workspace-1:user-1", "Example workspace")

    async def fetch_identity(access_token: str) -> ExternalPrincipal:
        fetched_tokens.append(access_token)
        return ExternalPrincipal("workspace-1:user-1", None)

    protocol = OAuthProtocol(
        authorization_params=(("owner", "user"),),
        scope_parameter=False,
        pkce="none",
        token_auth="client_secret_basic",  # noqa: S106
        token_encoding="json",  # noqa: S106
        identity_source="provider",
        extract_identity=extract_identity,
        fetch_identity=fetch_identity,
        request_headers=(("Notion-Version", "2026-03-11"),),
        revoke_token="access",  # noqa: S106
    )
    config = OAuthClientConfig(
        client_id="provider-client",
        client_secret=SecretStr("provider-secret"),
        authorization_url="https://provider.example.test/authorize",
        token_url="https://provider.example.test/token",  # noqa: S106
        revoke_url="https://provider.example.test/revoke",
        protocol=protocol,
    )
    PROVIDER_PLUGINS["gmail"] = replace(GMAIL_PROVIDER, oauth_config=lambda: config)

    class Response:
        def json(self) -> dict[str, str]:
            return {"access_token": "provider-access", "workspace_id": "workspace-1"}

    async def request_with_retries(method: str, url: str, **kwargs):
        sent.append({"method": method, "url": url, **kwargs})
        return Response()

    monkeypatch.setattr(exchange_module, "request_with_retries", request_with_retries)

    authorization_url = build_authorization_url(
        GMAIL_PROVIDER.manifest,
        state="provider-state",
        code_verifier="stored-but-not-sent",
    )
    assert authorization_url == (
        "https://provider.example.test/authorize?client_id=provider-client&"
        "redirect_uri=https%3A%2F%2Fapp.example.test%2Fintegrations%2Foauth%2Fcallback&"
        "response_type=code&state=provider-state&owner=user"
    )

    token_payload = await exchange_authorization_code(
        provider_key="gmail",
        code="provider-code",
        code_verifier="stored-but-not-sent",
    )
    await refresh_authorization_token(
        provider_key="gmail",
        refresh_token="provider-refresh",  # noqa: S106
    )
    await revoke_authorization_token(
        provider_key="gmail",
        token="provider-access",  # noqa: S106
    )

    expected_authorization = "Basic " + b64encode(b"provider-client:provider-secret").decode(
        "ascii"
    )
    for request in sent:
        assert request["headers"] == {
            "Notion-Version": "2026-03-11",
            "Authorization": expected_authorization,
        }
        assert "data" not in request
    assert sent[0]["json"] == {
        "code": "provider-code",
        "redirect_uri": "https://app.example.test/integrations/oauth/callback",
        "grant_type": "authorization_code",
    }
    assert sent[1]["json"] == {
        "refresh_token": "provider-refresh",
        "grant_type": "refresh_token",
    }
    assert sent[2]["json"] == {"token": "provider-access"}

    extracted = await resolve_external_principal(
        provider_key="gmail",
        access_token="provider-access",  # noqa: S106
        token_payload=token_payload,
    )
    fetched = await resolve_external_principal(
        provider_key="gmail",
        access_token="provider-access",  # noqa: S106
    )
    assert extracted == ExternalPrincipal("workspace-1:user-1", "Example workspace")
    assert fetched == ExternalPrincipal("workspace-1:user-1", None)
    assert fetched_tokens == ["provider-access"]


async def test_provider_identity_failure_does_not_expose_provider_values(
    isolated_google_oauth_settings: None,
) -> None:
    exposed_value = "provider-access-secret"

    async def rejected_identity(access_token: str) -> ExternalPrincipal:
        raise ValueError(access_token)

    config = replace(
        GMAIL_PROVIDER.oauth_config(),
        protocol=OAuthProtocol(
            identity_source="provider",
            fetch_identity=rejected_identity,
        ),
    )
    PROVIDER_PLUGINS["gmail"] = replace(GMAIL_PROVIDER, oauth_config=lambda: config)

    with pytest.raises(IntegrationAuthError) as exc_info:
        await resolve_external_principal(
            provider_key="gmail",
            access_token=exposed_value,
        )

    formatted_chain = "".join(format_exception(exc_info.value))
    assert exposed_value not in formatted_chain


def test_callback_connection_metadata_accepts_bounded_notion_fields() -> None:
    callback_module = import_module("services.integrations.connections.complete_oauth_callback")
    metadata = {
        "bot_id": "bot-1",
        "duplicated_template_id": "page-1",
        "workspace_icon": "https://example.com/icon.png",
        "workspace_id": "workspace-1",
        "workspace_name": "Example Organization",
    }

    assert (
        callback_module._validated_connection_metadata(
            metadata,
            provider_key="gmail",
        )
        == metadata
    )


@pytest.mark.parametrize(
    "metadata",
    [
        {"BadKey": "value"},
        {"api_key": "value"},
        {"code": "value"},
        {"token": "value"},
        {"id_token": "value"},
        {"client_secret": "value"},
        {"authorization_code": "value"},
        {"workspace_id": 1},
        {"workspace_id": "x" * 256},
        {f"key_{index}": "value" for index in range(17)},
    ],
)
def test_callback_connection_metadata_rejects_unbounded_or_secret_fields(
    metadata: object,
) -> None:
    callback_module = import_module("services.integrations.connections.complete_oauth_callback")

    with pytest.raises(IntegrationAuthError, match="metadata was rejected"):
        callback_module._validated_connection_metadata(
            metadata,
            provider_key="gmail",
        )


@pytest.mark.parametrize(
    "reserved_key",
    [
        "client_id",
        "code_challenge",
        "code_challenge_method",
        "redirect_uri",
        "response_type",
        "scope",
        "state",
    ],
)
def test_plugin_validation_rejects_reserved_authorization_parameters(
    reserved_key: str,
) -> None:
    config = replace(
        GMAIL_PROVIDER.oauth_config(),
        protocol=OAuthProtocol(authorization_params=((reserved_key, "overridden"),)),
    )
    plugin = replace(GMAIL_PROVIDER, oauth_config=lambda: config)

    with pytest.raises(RuntimeError, match="reserved authorization parameters"):
        _validate_plugin(plugin, expected_key="gmail")


def test_authorization_url_defensively_rejects_reserved_parameters(
    isolated_google_oauth_settings: None,
) -> None:
    config = replace(
        GMAIL_PROVIDER.oauth_config(),
        protocol=OAuthProtocol(authorization_params=(("state", "overridden"),)),
    )
    PROVIDER_PLUGINS["gmail"] = replace(GMAIL_PROVIDER, oauth_config=lambda: config)

    with pytest.raises(RuntimeError, match="override reserved fields: state"):
        build_authorization_url(
            GMAIL_PROVIDER.manifest,
            state="trusted-state",
            code_verifier="gmail-verifier",
        )


async def test_client_secret_basic_uses_literal_credentials(
    isolated_google_oauth_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchange_module = import_module("services.integrations.oauth.exchange_authorization_code")
    sent: dict[str, object] = {}
    config = OAuthClientConfig(
        client_id="client id+value",
        client_secret=SecretStr("secret+value&more"),
        authorization_url="https://provider.example.test/authorize",
        token_url="https://provider.example.test/token",  # noqa: S106
        revoke_url="https://provider.example.test/revoke",
        protocol=OAuthProtocol(token_auth="client_secret_basic"),  # noqa: S106
    )
    PROVIDER_PLUGINS["gmail"] = replace(GMAIL_PROVIDER, oauth_config=lambda: config)

    class Response:
        def json(self) -> dict[str, str]:
            return {"access_token": "provider-access"}

    async def request_with_retries(method: str, url: str, **kwargs):
        sent.update(kwargs)
        return Response()

    monkeypatch.setattr(exchange_module, "request_with_retries", request_with_retries)
    await exchange_authorization_code(
        provider_key="gmail",
        code="provider-code",
        code_verifier="provider-verifier",
    )

    encoded = b64encode(b"client id+value:secret+value&more").decode("ascii")
    assert sent["headers"] == {"Authorization": f"Basic {encoded}"}


async def test_oauth_protocol_rejects_malformed_json(
    isolated_google_oauth_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = import_module("services.integrations.oauth.exchange_authorization_code")

    class Response:
        def json(self):
            raise ValueError("malformed provider response")

    async def request_with_retries(method: str, url: str, **kwargs):
        return Response()

    monkeypatch.setattr(module, "request_with_retries", request_with_retries)
    with pytest.raises(IntegrationConnectionError):
        await exchange_authorization_code(
            provider_key="gmail",
            code="gmail-code",
            code_verifier="gmail-verifier",
        )


async def test_oauth_token_error_uses_provider_classifier(
    isolated_google_oauth_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.integrations import http as http_module

    config = GMAIL_PROVIDER.oauth_config()
    classified_config = replace(
        config,
        protocol=replace(
            config.protocol,
            classify_token_error=lambda payload: (
                "reauthorization_required" if payload.get("error") == "invalid_grant" else None
            ),
        ),
    )
    PROVIDER_PLUGINS["gmail"] = replace(
        GMAIL_PROVIDER,
        oauth_config=lambda: classified_config,
    )

    async_client_type = httpx2.AsyncClient

    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            400,
            headers={"Content-Type": "application/json"},
            json={"error": "invalid_grant", "error_description": "provider detail"},
        )

    monkeypatch.setattr(
        http_module.httpx2,
        "AsyncClient",
        lambda: async_client_type(transport=httpx2.MockTransport(handler)),
    )
    with pytest.raises(IntegrationAuthError) as exc_info:
        await refresh_authorization_token(
            provider_key="gmail",
            refresh_token="refresh-token",  # noqa: S106
        )

    assert exc_info.value.error_code == "reauthorization_required"
    assert exc_info.value.failure_disposition == "rejected"
    assert exc_info.value.user_message == "OAuth token response was rejected"
    assert "provider detail" not in str(exc_info.value)


async def test_oauth_unclassified_token_error_keeps_existing_contract(
    isolated_google_oauth_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = import_module("services.integrations.oauth.exchange_authorization_code")

    class Response:
        def json(self) -> dict[str, str]:
            return {"error": "unknown_error"}

    async def request_with_retries(*_args, **_kwargs) -> Response:
        return Response()

    monkeypatch.setattr(module, "request_with_retries", request_with_retries)
    with pytest.raises(IntegrationAuthError) as exc_info:
        await exchange_authorization_code(
            provider_key="gmail",
            code="gmail-code",
            code_verifier="gmail-verifier",
        )

    assert exc_info.value.error_code is None
    assert exc_info.value.user_message == "OAuth token response was rejected"


async def test_revocation_sends_token_in_form_body(
    isolated_google_oauth_settings: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = import_module("services.integrations.oauth.exchange_authorization_code")
    sent: dict[str, object] = {}

    async def request_with_retries(method: str, url: str, **kwargs):
        sent.update(method=method, url=url, **kwargs)

    monkeypatch.setattr(module, "request_with_retries", request_with_retries)
    token = uuid4().hex
    await revoke_authorization_token(provider_key="gmail", token=token)

    assert sent["method"] == "POST"
    assert sent["url"] == "https://oauth2.googleapis.com/revoke"
    assert sent["data"] == {"token": token}
    assert "params" not in sent
    assert token not in str(sent["url"])


async def test_missing_refresh_token_requires_reauthentication() -> None:
    credential = ExternalCredential(
        provider_key="gmail",
        auth_mode="oauth",
        principal_fingerprint="fingerprint",
    )

    with pytest.raises(IntegrationAuthError):
        await refresh_oauth_credential(credential)
