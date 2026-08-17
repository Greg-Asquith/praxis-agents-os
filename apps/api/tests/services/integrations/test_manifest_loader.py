"""Manifest invariants and settings-driven provider loading."""

import pytest
from pydantic import SecretStr

from core.settings import settings
from integrations.gmail.settings import gmail_settings
from integrations.google_ads.settings import google_ads_settings
from integrations.google_analytics.settings import google_analytics_settings
from services.agents.runtime.entity_references.registry import ENTITY_RESOLVERS
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from services.integrations.loader import _validate_plugin, load_enabled_providers
from services.integrations.manifest import (
    PROVIDER_MANIFESTS,
    IntegrationProviderManifest,
    register_provider_manifest,
)
from services.integrations.plugin import (
    PROVIDER_PLUGINS,
    IntegrationPreviewDefinition,
    IntegrationPreviewPayload,
    IntegrationProviderPlugin,
)


@pytest.fixture(autouse=True)
def clear_loaded_provider_state():
    for kind, resolver in tuple(ENTITY_RESOLVERS.items()):
        if resolver.provider_key is not None:
            ENTITY_RESOLVERS.pop(kind)
    for name in tuple(RUNTIME_TOOL_CATALOG):
        if name.startswith(
            ("airtable_", "bigquery_", "gmail_", "google_ads_", "google_analytics_")
        ):
            RUNTIME_TOOL_CATALOG.pop(name)
    yield
    PROVIDER_MANIFESTS.clear()
    PROVIDER_PLUGINS.clear()
    for kind, resolver in tuple(ENTITY_RESOLVERS.items()):
        if resolver.provider_key is not None:
            ENTITY_RESOLVERS.pop(kind)
    for name in tuple(RUNTIME_TOOL_CATALOG):
        if name.startswith(
            ("airtable_", "bigquery_", "gmail_", "google_ads_", "google_analytics_")
        ):
            RUNTIME_TOOL_CATALOG.pop(name)


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


def test_manifest_rejects_duplicate_and_invalid_contracts() -> None:
    PROVIDER_MANIFESTS.clear()
    register_provider_manifest(_oauth_manifest())
    with pytest.raises(RuntimeError, match="Duplicate"):
        register_provider_manifest(_oauth_manifest())
    with pytest.raises(RuntimeError, match="scopes"):
        register_provider_manifest(
            IntegrationProviderManifest(
                provider_key="no_scopes",
                display_name="No scopes",
                auth_modes=("oauth",),
                owner_scope="user",
            )
        )
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

    monkeypatch.setattr(
        settings,
        "INTEGRATIONS_ENABLED_PROVIDERS",
        ["airtable", "bigquery", "gmail", "google_ads", "google_analytics"],
    )
    load_enabled_providers()
    expected = ["airtable", "bigquery", "gmail", "google_ads", "google_analytics"]
    assert sorted(PROVIDER_MANIFESTS) == expected
    assert sorted(PROVIDER_PLUGINS) == expected
    assert not hasattr(settings, "INTEGRATIONS_AIRTABLE_ENABLED")
    assert not hasattr(settings, "GMAIL_OAUTH_CLIENT_ID")
    assert not hasattr(settings, "GOOGLE_ADS_OAUTH_CLIENT_ID")
    assert not hasattr(settings, "GOOGLE_ANALYTICS_OAUTH_CLIENT_ID")
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


def test_loader_rejects_google_analytics_sharing_google_ads_client(monkeypatch) -> None:
    PROVIDER_MANIFESTS.clear()
    PROVIDER_PLUGINS.clear()
    monkeypatch.setattr(
        settings,
        "INTEGRATIONS_ENABLED_PROVIDERS",
        ["google_ads", "google_analytics"],
    )
    monkeypatch.setattr(google_ads_settings, "GOOGLE_ADS_OAUTH_CLIENT_ID", "shared-client")
    monkeypatch.setattr(
        google_analytics_settings,
        "GOOGLE_ANALYTICS_OAUTH_CLIENT_ID",
        "shared-client",
    )

    with pytest.raises(RuntimeError, match="isolated client IDs"):
        load_enabled_providers()
    PROVIDER_MANIFESTS.clear()
    PROVIDER_PLUGINS.clear()


def test_provider_packages_own_distinct_oauth_credentials(monkeypatch) -> None:
    from integrations.gmail import oauth_config as gmail_oauth_config
    from integrations.google_ads import oauth_config as google_ads_oauth_config
    from integrations.google_analytics import oauth_config as google_analytics_oauth_config

    monkeypatch.setattr(gmail_settings, "GMAIL_OAUTH_CLIENT_ID", "gmail-client")
    monkeypatch.setattr(gmail_settings, "GMAIL_OAUTH_CLIENT_SECRET", SecretStr("gmail-secret"))
    monkeypatch.setattr(google_ads_settings, "GOOGLE_ADS_OAUTH_CLIENT_ID", "ads-client")
    monkeypatch.setattr(
        google_ads_settings,
        "GOOGLE_ADS_OAUTH_CLIENT_SECRET",
        SecretStr("ads-secret"),
    )
    monkeypatch.setattr(
        google_analytics_settings,
        "GOOGLE_ANALYTICS_OAUTH_CLIENT_ID",
        "analytics-client",
    )
    monkeypatch.setattr(
        google_analytics_settings,
        "GOOGLE_ANALYTICS_OAUTH_CLIENT_SECRET",
        SecretStr("analytics-secret"),
    )

    gmail_config = gmail_oauth_config()
    ads_config = google_ads_oauth_config()
    analytics_config = google_analytics_oauth_config()
    assert gmail_config.client_id == "gmail-client"
    assert ads_config.client_id == "ads-client"
    assert gmail_config.client_secret.get_secret_value() == "gmail-secret"
    assert ads_config.client_secret.get_secret_value() == "ads-secret"
    assert analytics_config.client_id == "analytics-client"
    assert analytics_config.client_secret.get_secret_value() == "analytics-secret"


def test_loader_fails_fast_for_unknown_provider(monkeypatch) -> None:
    PROVIDER_MANIFESTS.clear()
    PROVIDER_PLUGINS.clear()
    monkeypatch.setattr(settings, "INTEGRATIONS_ENABLED_PROVIDERS", ["does_not_exist"])
    with pytest.raises(RuntimeError, match="Unknown enabled"):
        load_enabled_providers()


def test_loader_requires_discovery_callable_when_manifest_advertises_it() -> None:
    plugin = IntegrationProviderPlugin(
        manifest=IntegrationProviderManifest(
            provider_key="example",
            display_name="Example",
            auth_modes=("oauth",),
            owner_scope="workspace",
            oauth_scopes=("scope",),
            resource_types=("example_resource",),
            requires_discovery=True,
        ),
        discover_resources=None,
    )
    with pytest.raises(RuntimeError, match="must implement discovery"):
        _validate_plugin(plugin, expected_key="example")


def test_loader_requires_a_registered_valid_metadata_sync_handler() -> None:
    invalid_kind = IntegrationProviderPlugin(
        manifest=_api_key_manifest(),
        discover_resources=None,
        metadata_sync_job_kind="Invalid-Kind",
    )
    with pytest.raises(RuntimeError, match="invalid metadata sync job kind"):
        _validate_plugin(invalid_kind, expected_key="example")

    missing_handler = IntegrationProviderPlugin(
        manifest=_api_key_manifest(),
        discover_resources=None,
        metadata_sync_job_kind="integrations.missing_handler",
    )
    with pytest.raises(RuntimeError, match="handler is not registered"):
        _validate_plugin(missing_handler, expected_key="example")


def test_loader_validates_provider_preview_definitions() -> None:
    async def fetch_preview(db, connection, ref) -> IntegrationPreviewPayload:
        return IntegrationPreviewPayload(content_type="text", content=ref, meta={})

    definition = IntegrationPreviewDefinition(
        kind="message",
        operation="preview_message",
        fetch=fetch_preview,
    )
    plugin = IntegrationProviderPlugin(
        manifest=_api_key_manifest(),
        discover_resources=None,
        preview_definitions=(definition, definition),
    )
    with pytest.raises(RuntimeError, match="Duplicate integration preview kind"):
        _validate_plugin(plugin, expected_key="example")

    invalid_plugin = IntegrationProviderPlugin(
        manifest=_api_key_manifest(),
        discover_resources=None,
        preview_definitions=(
            IntegrationPreviewDefinition(
                kind="Invalid-Kind",
                operation="preview_message",
                fetch=fetch_preview,
            ),
        ),
    )
    with pytest.raises(RuntimeError, match="lowercase snake_case"):
        _validate_plugin(invalid_plugin, expected_key="example")
