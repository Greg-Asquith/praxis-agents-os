"""Manifest invariants and settings-driven provider loading."""

import pytest

from core.settings import settings
from services.integrations.loader import _validate_plugin, load_enabled_providers
from services.integrations.manifest import (
    PROVIDER_MANIFESTS,
    IntegrationProviderManifest,
    register_provider_manifest,
)
from services.integrations.plugin import IntegrationProviderPlugin


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
    assert not hasattr(settings, "INTEGRATIONS_AIRTABLE_ENABLED")
    PROVIDER_MANIFESTS.clear()


def test_loader_fails_fast_for_unknown_provider(monkeypatch) -> None:
    PROVIDER_MANIFESTS.clear()
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
