"""Provider-owned OAuth credentials stay isolated across Google services."""

from collections.abc import Iterator
from importlib import import_module
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

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
from services.integrations.oauth import (
    build_authorization_url,
    exchange_authorization_code,
    revoke_authorization_token,
)
from services.integrations.plugin import PROVIDER_PLUGINS


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


def test_google_identity_lookup_uses_the_oidc_userinfo_endpoint() -> None:
    module = import_module("services.integrations.oauth.fetch_external_principal")
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
