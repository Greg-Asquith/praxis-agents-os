"""Microsoft login uses the configured tenant throughout the OAuth flow."""

from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from pydantic import ValidationError

from core.auth.oauth_providers import retrying
from core.auth.oauth_providers.microsoft import MicrosoftOAuthProvider
from core.settings import settings
from core.settings.auth import AuthSettingsMixin
from core.settings.base import SettingsBase

TENANT_ID = "b2c4d170-11e8-43a7-943e-a758a11b48d4"


class LoginSettings(SettingsBase, AuthSettingsMixin):
    pass


def test_microsoft_login_reads_tenant_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MICROSOFT_AZURE_TENANT_ID", f" {TENANT_ID} ")

    assert LoginSettings().MICROSOFT_AZURE_TENANT_ID == TENANT_ID


def test_microsoft_login_defaults_to_common(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MICROSOFT_AZURE_TENANT_ID", raising=False)

    assert LoginSettings().MICROSOFT_AZURE_TENANT_ID == "common"


@pytest.mark.parametrize("tenant", ["", " ", "../common", "https://example.com", "tenant?x=1"])
def test_microsoft_login_rejects_invalid_tenant(tenant: str) -> None:
    with pytest.raises(ValidationError, match="MICROSOFT_AZURE_TENANT_ID"):
        LoginSettings(MICROSOFT_AZURE_TENANT_ID=tenant)


@pytest.mark.parametrize(
    "tenant", [TENANT_ID, "example.onmicrosoft.com", "common", "organizations", "consumers"]
)
async def test_microsoft_login_uses_tenant_for_authorisation_and_tokens(
    monkeypatch: pytest.MonkeyPatch, tenant: str
) -> None:
    configured = LoginSettings(MICROSOFT_AZURE_TENANT_ID=tenant)
    monkeypatch.setattr(settings, "MICROSOFT_AZURE_TENANT_ID", configured.MICROSOFT_AZURE_TENANT_ID)
    monkeypatch.setattr(settings, "MICROSOFT_OAUTH_CLIENT_ID", "login-client")
    monkeypatch.setattr(settings, "MICROSOFT_GRAPH_TENANT", "other.example.com")
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json={"access_token": "test-access-token"}, request=request)

    original_client = httpx2.AsyncClient
    monkeypatch.setattr(
        retrying.httpx2,
        "AsyncClient",
        lambda: original_client(transport=httpx2.MockTransport(handler)),
    )
    provider = MicrosoftOAuthProvider()
    redirect_uri = "http://localhost:3000/oauth/callback"
    url = urlsplit(await provider.get_authorization_url("browser-bound-state", redirect_uri))

    assert url.scheme == "https"
    assert url.netloc == "login.microsoftonline.com"
    assert url.path == f"/{tenant}/oauth2/v2.0/authorize"
    query = parse_qs(url.query)
    assert query["client_id"] == ["login-client"]
    assert query["redirect_uri"] == [redirect_uri]
    assert query["state"] == ["browser-bound-state"]

    await provider.exchange_code("test-code", redirect_uri)
    await provider.refresh_access_token("test-refresh-token")

    assert [str(request.url) for request in requests] == [
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
    ]
    assert [parse_qs(request.content.decode())["grant_type"] for request in requests] == [
        ["authorization_code"],
        ["refresh_token"],
    ]
