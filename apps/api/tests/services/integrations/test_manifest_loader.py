# apps/api/tests/services/integrations/test_manifest_loader.py

"""Manifest invariants and settings-driven provider loading."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from core.settings import settings
from integrations.gmail.settings import gmail_settings
from integrations.google_ads.settings import google_ads_settings
from services.agents.runtime.entity_references.registry import ENTITY_RESOLVERS
from services.agents.runtime.tools.contract import (
    RuntimeToolDefinition,
    ToolFieldPresentation,
    ToolPresentation,
)
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.integrations.loader import _validate_plugin, load_enabled_providers
from services.integrations.manifest import (
    PROVIDER_MANIFESTS,
    IntegrationProviderManifest,
    register_provider_manifest,
)
from services.integrations.plugin import (
    PROVIDER_PLUGINS,
    ExternalPrincipal,
    IntegrationProviderPlugin,
    OAuthClientConfig,
    OAuthProtocol,
)


@pytest.fixture(autouse=True)
def clear_loaded_provider_state():
    original_manifests = dict(PROVIDER_MANIFESTS)
    original_plugins = dict(PROVIDER_PLUGINS)
    original_resolvers = {
        kind: resolver
        for kind, resolver in ENTITY_RESOLVERS.items()
        if resolver.provider_key is not None
    }
    original_tools = {
        name: definition
        for name, definition in RUNTIME_TOOL_CATALOG.items()
        if name.startswith(
            (
                "airtable_",
                "bigquery_",
                "gmail_",
                "google_ads_",
                "google_analytics_",
                "google_search_console_",
                "meta_ads_",
                "notion_",
                "outlook_calendar_",
                "outlook_mail_",
                "sharepoint_",
            )
        )
    }
    PROVIDER_MANIFESTS.clear()
    PROVIDER_PLUGINS.clear()
    for kind, resolver in tuple(ENTITY_RESOLVERS.items()):
        if resolver.provider_key is not None:
            ENTITY_RESOLVERS.pop(kind)
    for name in tuple(RUNTIME_TOOL_CATALOG):
        if name.startswith(
            (
                "airtable_",
                "bigquery_",
                "gmail_",
                "google_ads_",
                "google_analytics_",
                "google_search_console_",
                "meta_ads_",
                "notion_",
                "outlook_calendar_",
                "outlook_mail_",
                "sharepoint_",
            )
        ):
            RUNTIME_TOOL_CATALOG.pop(name)
    yield
    PROVIDER_MANIFESTS.clear()
    PROVIDER_MANIFESTS.update(original_manifests)
    PROVIDER_PLUGINS.clear()
    PROVIDER_PLUGINS.update(original_plugins)
    for kind, resolver in tuple(ENTITY_RESOLVERS.items()):
        if resolver.provider_key is not None:
            ENTITY_RESOLVERS.pop(kind)
    ENTITY_RESOLVERS.update(original_resolvers)
    for name in tuple(RUNTIME_TOOL_CATALOG):
        if name.startswith(
            (
                "airtable_",
                "bigquery_",
                "gmail_",
                "google_ads_",
                "google_analytics_",
                "google_search_console_",
                "meta_ads_",
                "notion_",
                "outlook_calendar_",
                "outlook_mail_",
                "sharepoint_",
            )
        ):
            RUNTIME_TOOL_CATALOG.pop(name)
    RUNTIME_TOOL_CATALOG.update(original_tools)


def _oauth_manifest(key: str = "example") -> IntegrationProviderManifest:
    return IntegrationProviderManifest(
        provider_key=key,
        display_name="Example",
        auth_modes=("oauth",),
        owner_scope="user",
        oauth_scopes=("scope",),
    )


def _api_key_manifest(key: str = "example") -> IntegrationProviderManifest:
    return IntegrationProviderManifest(
        provider_key=key,
        display_name="Example",
        auth_modes=("api_key",),
        owner_scope="workspace",
        required_form_fields=("api_key",),
    )


async def _fetch_provider_identity(access_token: str) -> ExternalPrincipal:
    return ExternalPrincipal(external_id=access_token, label=None)


def _notion_protocol() -> OAuthProtocol:
    return OAuthProtocol(
        authorization_params=(("owner", "user"),),
        scope_parameter=False,
        pkce="none",
        token_auth="client_secret_basic",  # noqa: S106 - protocol enum, not a credential
        token_encoding="json",  # noqa: S106 - protocol enum, not a credential
        identity_source="provider",
        fetch_identity=_fetch_provider_identity,
        request_headers=(("Notion-Version", "2026-03-11"),),
        revoke_token="access",  # noqa: S106 - protocol enum, not a credential
    )


def _oauth_plugin(
    *,
    key: str = "example",
    oauth_scopes: tuple[str, ...] = ("scope",),
    protocol: OAuthProtocol | None = None,
) -> IntegrationProviderPlugin:
    manifest = replace(_oauth_manifest(key), oauth_scopes=oauth_scopes)
    endpoint_root = "https://accounts.example.com"
    config = OAuthClientConfig(
        client_id=f"{key}-client",
        client_secret=SecretStr(f"{key}-secret"),
        authorization_url=f"{endpoint_root}/authorize",
        token_url=f"{endpoint_root}/token",
        revoke_url=f"{endpoint_root}/revoke",
        protocol=protocol or OAuthProtocol(),
    )
    return IntegrationProviderPlugin(
        manifest=manifest,
        discover_resources=None,
        oauth_config=lambda: config,
    )


def test_manifest_rejects_duplicate_and_invalid_contracts() -> None:
    PROVIDER_MANIFESTS.clear()
    register_provider_manifest(_oauth_manifest())
    with pytest.raises(RuntimeError, match="Duplicate"):
        register_provider_manifest(_oauth_manifest())
    register_provider_manifest(replace(_oauth_manifest("no_scopes"), oauth_scopes=()))
    with pytest.raises(RuntimeError, match="form fields"):
        register_provider_manifest(
            IntegrationProviderManifest(
                provider_key="no_fields",
                display_name="No fields",
                auth_modes=("api_key",),
                owner_scope="workspace",
            )
        )
    PROVIDER_MANIFESTS.clear()


def test_loader_uses_one_allowlist_for_every_provider(monkeypatch) -> None:
    PROVIDER_MANIFESTS.clear()
    PROVIDER_PLUGINS.clear()
    monkeypatch.setattr(settings, "INTEGRATIONS_ENABLED_PROVIDERS", [])
    load_enabled_providers()
    assert PROVIDER_MANIFESTS == {}

    from services.integrations import loader

    import_module = loader.importlib.import_module
    notion_module = SimpleNamespace(
        PROVIDER=_oauth_plugin(
            key="notion",
            oauth_scopes=(),
            protocol=_notion_protocol(),
        )
    )

    def import_provider_module(name: str):
        if name == "integrations.notion":
            return notion_module
        return import_module(name)

    monkeypatch.setattr(loader.importlib, "import_module", import_provider_module)
    monkeypatch.setattr(
        settings,
        "INTEGRATIONS_ENABLED_PROVIDERS",
        [
            "airtable",
            "bigquery",
            "gmail",
            "google_ads",
            "google_analytics",
            "google_search_console",
            "meta_ads",
            "notion",
            "outlook_calendar",
            "outlook_mail",
            "sharepoint",
        ],
    )
    load_enabled_providers()
    expected = [
        "airtable",
        "bigquery",
        "gmail",
        "google_ads",
        "google_analytics",
        "google_search_console",
        "meta_ads",
        "notion",
        "outlook_calendar",
        "outlook_mail",
        "sharepoint",
    ]
    assert sorted(PROVIDER_MANIFESTS) == expected
    assert sorted(PROVIDER_PLUGINS) == expected
    assert not hasattr(settings, "INTEGRATIONS_AIRTABLE_ENABLED")
    assert not hasattr(settings, "GMAIL_OAUTH_CLIENT_ID")
    assert not hasattr(settings, "GOOGLE_ADS_OAUTH_CLIENT_ID")
    assert not hasattr(settings, "GOOGLE_ANALYTICS_OAUTH_CLIENT_ID")
    assert not hasattr(settings, "OUTLOOK_MAIL_OAUTH_CLIENT_ID")
    assert not hasattr(settings, "OUTLOOK_CALENDAR_OAUTH_CLIENT_ID")
    assert not hasattr(settings, "SHAREPOINT_OAUTH_CLIENT_ID")
    assert not hasattr(settings, "GOOGLE_SEARCH_CONSOLE_OAUTH_CLIENT_ID")
    PROVIDER_MANIFESTS.clear()
    PROVIDER_PLUGINS.clear()


def test_loader_rejects_shared_oauth_client_ids(monkeypatch) -> None:
    PROVIDER_MANIFESTS.clear()
    PROVIDER_PLUGINS.clear()
    monkeypatch.setattr(settings, "INTEGRATIONS_ENABLED_PROVIDERS", ["gmail", "google_ads"])
    monkeypatch.setattr(gmail_settings, "GMAIL_OAUTH_CLIENT_ID", "shared-client")
    monkeypatch.setattr(google_ads_settings, "GOOGLE_ADS_OAUTH_CLIENT_ID", "shared-client")

    with pytest.raises(RuntimeError, match="isolated client IDs"):
        load_enabled_providers()
    PROVIDER_MANIFESTS.clear()
    PROVIDER_PLUGINS.clear()


def test_loader_fails_fast_for_unknown_provider(monkeypatch) -> None:
    PROVIDER_MANIFESTS.clear()
    PROVIDER_PLUGINS.clear()
    monkeypatch.setattr(settings, "INTEGRATIONS_ENABLED_PROVIDERS", ["does_not_exist"])
    with pytest.raises(RuntimeError, match="Unknown enabled"):
        load_enabled_providers()


def test_loader_validates_remote_revocation_configuration() -> None:
    without_remote_revocation = _oauth_plugin(
        protocol=OAuthProtocol(revoke_token="none"),  # noqa: S106 - protocol enum
    )
    assert without_remote_revocation.oauth_config is not None
    without_remote_revocation_config = without_remote_revocation.oauth_config()
    without_remote_revocation = replace(
        without_remote_revocation,
        oauth_config=lambda: replace(
            without_remote_revocation_config,
            revoke_url="",
        ),
    )
    assert _validate_plugin(without_remote_revocation, expected_key="example") is not None

    missing_url = _oauth_plugin()
    assert missing_url.oauth_config is not None
    missing_url_config = missing_url.oauth_config()
    missing_url = replace(
        missing_url,
        oauth_config=lambda: replace(
            missing_url_config,
            revoke_url="",
        ),
    )
    with pytest.raises(RuntimeError, match="must declare a revocation URL"):
        _validate_plugin(missing_url, expected_key="example")

    unexpected_url = _oauth_plugin(
        protocol=OAuthProtocol(revoke_token="none"),  # noqa: S106 - protocol enum
    )
    with pytest.raises(RuntimeError, match="must not declare a revocation URL"):
        _validate_plugin(unexpected_url, expected_key="example")


@pytest.mark.parametrize(
    ("oauth_scopes", "protocol", "message"),
    [
        ((), OAuthProtocol(), "must declare scopes"),
        (
            ("scope",),
            OAuthProtocol(fetch_identity=_fetch_provider_identity),
            "must not declare provider identity callables",
        ),
    ],
)
def test_loader_rejects_inconsistent_oauth_protocols(
    oauth_scopes: tuple[str, ...],
    protocol: OAuthProtocol,
    message: str,
) -> None:
    with pytest.raises(RuntimeError, match=message):
        _validate_plugin(
            _oauth_plugin(oauth_scopes=oauth_scopes, protocol=protocol),
            expected_key="example",
        )


@pytest.mark.parametrize(
    ("entity_kind", "file_resolver_owner", "allowed"),
    [
        ("file", "core", True),
        ("agent", "core", False),
        ("file", "example", False),
    ],
)
def test_loader_allows_only_core_file_argument_fields_without_provider_resolvers(
    monkeypatch: pytest.MonkeyPatch,
    entity_kind: str,
    file_resolver_owner: str,
    allowed: bool,
) -> None:
    if file_resolver_owner == "missing":
        monkeypatch.delitem(ENTITY_RESOLVERS, "file")
    elif file_resolver_owner != "core":
        monkeypatch.setitem(
            ENTITY_RESOLVERS,
            "file",
            replace(ENTITY_RESOLVERS["file"], provider_key=file_resolver_owner),
        )

    async def use_entity(source: str) -> str:
        return source

    plugin = IntegrationProviderPlugin(
        manifest=_api_key_manifest(),
        discover_resources=None,
        tool_definitions=(
            RuntimeToolDefinition(
                name="example_use_entity",
                provider="example",
                function=use_entity,
                description="Uses an entity.",
                presentation=ToolPresentation(
                    arg_fields=(
                        ToolFieldPresentation(
                            key="source", label="Source", format="entity", entity_kind=entity_kind
                        ),
                    ),
                ),
            ),
        ),
    )
    if allowed:
        assert _validate_plugin(plugin, expected_key="example") is None
    else:
        with pytest.raises(RuntimeError, match=f"provider-owned resolvers: {entity_kind}"):
            _validate_plugin(plugin, expected_key="example")
