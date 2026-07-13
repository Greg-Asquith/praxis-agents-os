"""Manifest invariants and settings-driven provider loading."""

import pytest
from pydantic import SecretStr

from core.settings import settings
from integrations.gmail.settings import gmail_settings
from integrations.google_ads.settings import google_ads_settings
from services.integrations.loader import _validate_plugin, load_enabled_providers
from services.integrations.manifest import (
    PROVIDER_MANIFESTS,
    IntegrationProviderManifest,
    register_provider_manifest,
)
from services.integrations.plugin import PROVIDER_PLUGINS, IntegrationProviderPlugin


def _oauth_manifest(key: str = "example") -> IntegrationProviderManifest:
    return IntegrationProviderManifest(
        provider_key=key,
        display_name="Example",
        auth_modes=("oauth",),
        owner_scope="user",
        oauth_scopes=("scope",),
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
        ["airtable", "gmail", "google_ads"],
    )
    load_enabled_providers()
    assert sorted(PROVIDER_MANIFESTS) == ["airtable", "gmail", "google_ads"]
    assert sorted(PROVIDER_PLUGINS) == ["airtable", "gmail", "google_ads"]
    assert not hasattr(settings, "INTEGRATIONS_AIRTABLE_ENABLED")
    assert not hasattr(settings, "GMAIL_OAUTH_CLIENT_ID")
    assert not hasattr(settings, "GOOGLE_ADS_OAUTH_CLIENT_ID")
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


def test_provider_packages_own_distinct_oauth_credentials(monkeypatch) -> None:
    from integrations.gmail import oauth_config as gmail_oauth_config
    from integrations.google_ads import oauth_config as google_ads_oauth_config

    monkeypatch.setattr(gmail_settings, "GMAIL_OAUTH_CLIENT_ID", "gmail-client")
    monkeypatch.setattr(gmail_settings, "GMAIL_OAUTH_CLIENT_SECRET", SecretStr("gmail-secret"))
    monkeypatch.setattr(google_ads_settings, "GOOGLE_ADS_OAUTH_CLIENT_ID", "ads-client")
    monkeypatch.setattr(
        google_ads_settings,
        "GOOGLE_ADS_OAUTH_CLIENT_SECRET",
        SecretStr("ads-secret"),
    )

    gmail_config = gmail_oauth_config()
    ads_config = google_ads_oauth_config()
    assert gmail_config.client_id == "gmail-client"
    assert ads_config.client_id == "ads-client"
    assert gmail_config.client_secret.get_secret_value() == "gmail-secret"
    assert ads_config.client_secret.get_secret_value() == "ads-secret"


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
