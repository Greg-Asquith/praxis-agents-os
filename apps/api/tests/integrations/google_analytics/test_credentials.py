"""Google Analytics runtime credential construction contracts."""

from types import SimpleNamespace
from uuid import uuid4

from integrations.google_analytics.discover_resources import ANALYTICS_READONLY_SCOPE
from integrations.google_analytics.tools.utils import client as client_module
from tests.integrations.google_analytics.support import property_entry


async def test_oauth_client_refreshes_through_the_shared_credential_seam(monkeypatch) -> None:
    credential = SimpleNamespace(auth_mode="oauth", id=uuid4())
    forces: list[bool] = []

    async def get_credential(*_args, **_kwargs):
        return credential

    async def ensure_fresh(*_args, force: bool, **_kwargs):
        forces.append(force)
        return SimpleNamespace(access_token="fresh-token")  # noqa: S106 -- test credential

    monkeypatch.setattr(client_module, "get_usable_connection_credential", get_credential)
    monkeypatch.setattr(client_module, "ensure_fresh_credential", ensure_fresh)
    client = await client_module.google_analytics_client_for_principal(
        object(),
        actor=SimpleNamespace(id=uuid4()),
        workspace=SimpleNamespace(id=uuid4()),
        entry=property_entry(),
    )

    assert await client._access_token(False) == "fresh-token"
    assert await client._access_token(True) == "fresh-token"
    assert forces == [False, True]


async def test_service_account_client_resolves_secret_and_caches_token_provider(
    monkeypatch,
) -> None:
    credential = SimpleNamespace(
        auth_mode="service_account",
        id=uuid4(),
        secret_provider="local",  # noqa: S106 -- test secret reference
        secret_name="credential-name",  # noqa: S106 -- test secret reference
        secret_version="version-1",  # noqa: S106 -- test secret reference
    )
    captured: dict[str, object] = {"constructors": 0}

    async def get_credential(*_args, **_kwargs):
        return credential

    async def resolve(*_args, **_kwargs):
        return '{"type":"service_account"}'

    def parse(raw: str, *, provider_key: str):
        captured.update(raw=raw, parse_provider_key=provider_key)
        return SimpleNamespace()

    class TokenProvider:
        def __init__(self, _credentials, *, provider_key: str, scope: str) -> None:
            captured["constructors"] = int(captured["constructors"]) + 1
            captured.update(provider_key=provider_key, scope=scope)

        async def access_token(self, force: bool = False) -> str:
            return "forced-token" if force else "cached-token"

    client_module._SERVICE_ACCOUNT_PROVIDERS.clear()
    monkeypatch.setattr(client_module, "get_usable_connection_credential", get_credential)
    monkeypatch.setattr(client_module, "resolve_secret", resolve)
    monkeypatch.setattr(client_module, "parse_google_service_account_json", parse)
    monkeypatch.setattr(client_module, "GoogleServiceAccountTokenProvider", TokenProvider)
    actor = SimpleNamespace(id=uuid4())
    workspace = SimpleNamespace(id=uuid4())
    entry = property_entry()

    first = await client_module.google_analytics_client_for_principal(
        object(), actor=actor, workspace=workspace, entry=entry
    )
    second = await client_module.google_analytics_client_for_principal(
        object(), actor=actor, workspace=workspace, entry=entry
    )

    assert await first._access_token(False) == "cached-token"
    assert await second._access_token(True) == "forced-token"
    assert captured == {
        "constructors": 1,
        "raw": '{"type":"service_account"}',
        "parse_provider_key": "google_analytics",
        "provider_key": "google_analytics",
        "scope": ANALYTICS_READONLY_SCOPE,
    }
    assert client_module.google_analytics_available() is True
