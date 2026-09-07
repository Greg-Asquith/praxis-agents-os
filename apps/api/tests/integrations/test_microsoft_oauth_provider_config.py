# apps/api/tests/integrations/test_microsoft_oauth_provider_config.py

"""OAuth wire-contract coverage shared by the Microsoft provider packages."""

import json
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx2
import pytest
from pydantic import SecretStr

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationNotFoundError,
    IntegrationPermissionError,
    IntegrationValidationError,
)
from core.settings import settings
from integrations.outlook_calendar import PROVIDER as CALENDAR_PROVIDER
from integrations.outlook_calendar.settings import outlook_calendar_settings
from integrations.outlook_mail import PROVIDER as MAIL_PROVIDER
from integrations.outlook_mail.settings import outlook_mail_settings
from integrations.sharepoint import PROVIDER as SHAREPOINT_PROVIDER
from integrations.sharepoint.settings import sharepoint_settings
from services.integrations.microsoft_graph import graph_response_error
from services.integrations.microsoft_graph.entra import validate_entra_tenant
from services.integrations.oauth import (
    build_authorization_url,
    exchange_authorization_code,
    refresh_authorization_token,
)
from services.integrations.oauth.utils import code_challenge
from services.integrations.plugin import PROVIDER_PLUGINS, IntegrationProviderPlugin

TENANT_ID = "b2c4d170-11e8-43a7-943e-a758a11b48d4"
REDIRECT_URI = "https://app.example.test/integrations/oauth/callback"
PROVIDERS = (
    ("outlook_mail", MAIL_PROVIDER, outlook_mail_settings, "OUTLOOK_MAIL"),
    ("outlook_calendar", CALENDAR_PROVIDER, outlook_calendar_settings, "OUTLOOK_CALENDAR"),
    ("sharepoint", SHAREPOINT_PROVIDER, sharepoint_settings, "SHAREPOINT"),
)


@pytest.fixture
def microsoft_oauth_plugins(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    original = dict(PROVIDER_PLUGINS)
    monkeypatch.setattr(settings, "INTEGRATIONS_OAUTH_REDIRECT_URI", REDIRECT_URI)
    for provider_key, provider, provider_settings, prefix in PROVIDERS:
        PROVIDER_PLUGINS[provider_key] = provider
        monkeypatch.setattr(
            provider_settings, f"{prefix}_OAUTH_CLIENT_ID", f"{provider_key}-client"
        )
        monkeypatch.setattr(
            provider_settings,
            f"{prefix}_OAUTH_CLIENT_SECRET",
            SecretStr(f"{provider_key}-secret"),
        )
        monkeypatch.setattr(provider_settings, f"{prefix}_OAUTH_TENANT", "")
    yield
    PROVIDER_PLUGINS.clear()
    PROVIDER_PLUGINS.update(original)


@pytest.mark.parametrize("tenant", [TENANT_ID, "organizations"])
@pytest.mark.parametrize("provider_key,provider,provider_settings,prefix", PROVIDERS)
def test_microsoft_authorization_url_has_the_exact_provider_contract(
    microsoft_oauth_plugins: None,
    monkeypatch: pytest.MonkeyPatch,
    tenant: str,
    provider_key: str,
    provider: IntegrationProviderPlugin,
    provider_settings: object,
    prefix: str,
) -> None:
    monkeypatch.setattr(settings, "MICROSOFT_GRAPH_TENANT", tenant)

    url = build_authorization_url(
        provider.manifest,
        state="state",
        code_verifier="verifier",
    )
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.path == f"/{tenant}/oauth2/v2.0/authorize"
    assert query == {
        "client_id": [f"{provider_key}-client"],
        "code_challenge": [code_challenge("verifier")],
        "code_challenge_method": ["S256"],
        "prompt": ["select_account"],
        "redirect_uri": [REDIRECT_URI],
        "response_mode": ["query"],
        "response_type": ["code"],
        "scope": [" ".join(provider.manifest.oauth_scopes)],
        "state": ["state"],
    }


@pytest.mark.parametrize("provider_key,provider,provider_settings,prefix", PROVIDERS)
def test_package_tenant_override_wins_for_each_microsoft_provider(
    microsoft_oauth_plugins: None,
    monkeypatch: pytest.MonkeyPatch,
    provider_key: str,
    provider: IntegrationProviderPlugin,
    provider_settings: object,
    prefix: str,
) -> None:
    monkeypatch.setattr(settings, "MICROSOFT_GRAPH_TENANT", TENANT_ID)
    monkeypatch.setattr(provider_settings, f"{prefix}_OAUTH_TENANT", "organizations")

    assert provider.oauth_config is not None
    assert "/organizations/" in provider.oauth_config().authorization_url


@pytest.mark.parametrize("provider_key,provider,provider_settings,prefix", PROVIDERS)
def test_configured_microsoft_provider_uses_its_effective_tenant(
    provider_key: str,
    provider: IntegrationProviderPlugin,
    provider_settings: object,
    prefix: str,
) -> None:
    client_id = str(getattr(provider_settings, f"{prefix}_OAUTH_CLIENT_ID"))
    client_secret = getattr(
        provider_settings,
        f"{prefix}_OAUTH_CLIENT_SECRET",
    ).get_secret_value()
    tenant_override = str(getattr(provider_settings, f"{prefix}_OAUTH_TENANT"))
    effective_tenant = tenant_override or settings.MICROSOFT_GRAPH_TENANT
    required_values = (client_id, client_secret, effective_tenant)
    if any(
        not value.strip() or value.strip().casefold() == "disabled" for value in required_values
    ):
        pytest.skip(f"{provider_key} OAuth environment is not configured")

    assert provider.oauth_config is not None
    expected_tenant = validate_entra_tenant(effective_tenant)
    assert f"/{expected_tenant}/" in provider.oauth_config().authorization_url


@pytest.mark.parametrize("tenant", ["", "common", "consumers", "not a tenant"])
@pytest.mark.parametrize("provider_key,provider,provider_settings,prefix", PROVIDERS)
def test_each_microsoft_provider_rejects_an_invalid_effective_tenant(
    microsoft_oauth_plugins: None,
    monkeypatch: pytest.MonkeyPatch,
    tenant: str,
    provider_key: str,
    provider: IntegrationProviderPlugin,
    provider_settings: object,
    prefix: str,
) -> None:
    monkeypatch.setattr(settings, "MICROSOFT_GRAPH_TENANT", tenant)

    assert provider.oauth_config is not None
    with pytest.raises(ValueError, match="Microsoft Graph tenant"):
        provider.oauth_config()


@pytest.mark.parametrize("provider_key,provider,provider_settings,prefix", PROVIDERS)
async def test_token_exchange_uses_each_microsoft_application_and_fixture(
    microsoft_oauth_plugins: None,
    monkeypatch: pytest.MonkeyPatch,
    provider_key: str,
    provider: IntegrationProviderPlugin,
    provider_settings: object,
    prefix: str,
) -> None:
    module = __import__(
        "services.integrations.oauth.exchange_authorization_code",
        fromlist=["request_with_retries"],
    )
    fixture_path = Path(__file__).parent / provider_key / "fixtures" / "token_response.json"
    fixture = json.loads(fixture_path.read_text())
    sent: dict[str, object] = {}

    class Response:
        def json(self) -> dict[str, object]:
            return fixture

    async def request_with_retries(method: str, url: str, **kwargs):
        sent.update({"method": method, "url": url, **kwargs})
        return Response()

    monkeypatch.setattr(settings, "MICROSOFT_GRAPH_TENANT", TENANT_ID)
    monkeypatch.setattr(module, "request_with_retries", request_with_retries)

    result = await exchange_authorization_code(
        provider_key=provider_key,
        code="authorization-code",
        code_verifier="verifier",
    )

    assert result == fixture
    assert sent["url"] == f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    assert sent["data"] == {
        "client_id": f"{provider_key}-client",
        "client_secret": f"{provider_key}-secret",
        "code": "authorization-code",
        "code_verifier": "verifier",
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }


@pytest.mark.parametrize("provider_key", [item[0] for item in PROVIDERS])
async def test_token_error_fixture_requires_reauthorization(
    microsoft_oauth_plugins: None,
    monkeypatch: pytest.MonkeyPatch,
    provider_key: str,
) -> None:
    from services.integrations import http as http_module

    fixture_path = Path(__file__).parent / provider_key / "fixtures" / "token_error.json"
    fixture = json.loads(fixture_path.read_text())
    async_client_type = httpx2.AsyncClient

    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            400,
            headers={"Content-Type": "application/json"},
            json=fixture,
        )

    monkeypatch.setattr(settings, "MICROSOFT_GRAPH_TENANT", TENANT_ID)
    monkeypatch.setattr(
        http_module.httpx2,
        "AsyncClient",
        lambda: async_client_type(transport=httpx2.MockTransport(handler)),
    )

    with pytest.raises(IntegrationAuthError) as exc_info:
        await refresh_authorization_token(
            provider_key=provider_key,
            refresh_token="refresh-token",  # noqa: S106
        )
    assert exc_info.value.error_code == "reauthorization_required"


@pytest.mark.parametrize(
    ("provider_key", "status", "error_type"),
    [
        ("outlook_mail", 400, IntegrationValidationError),
        ("outlook_calendar", 403, IntegrationPermissionError),
        ("sharepoint", 404, IntegrationNotFoundError),
    ],
)
def test_graph_error_fixtures_use_typed_provider_errors(
    provider_key: str,
    status: int,
    error_type: type[Exception],
) -> None:
    fixture_path = Path(__file__).parent / provider_key / "fixtures" / "graph_error.json"
    response = httpx2.Response(
        status,
        headers={"Content-Type": "application/json"},
        json=json.loads(fixture_path.read_text()),
    )

    error = graph_response_error(
        response,
        provider_key=provider_key,
        operation="discover_resources",
    )

    assert isinstance(error, error_type)
