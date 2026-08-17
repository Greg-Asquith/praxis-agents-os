"""Google Analytics provider manifest contracts."""

from integrations.google_analytics import PROVIDER
from integrations.google_analytics.discover_resources import ANALYTICS_READONLY_SCOPE
from integrations.google_analytics.tools.utils.bindings import (
    GOOGLE_ANALYTICS_BINDING,
    RESULTS_FIELD,
)
from services.agents.runtime.tools.contract import VALID_TOOL_ICONS
from services.integrations.loader import _validate_plugin
from services.integrations.oauth.fetch_external_principal import GOOGLE_PROVIDER_KEYS


def test_manifest_declares_read_only_workspace_property_provider() -> None:
    manifest = PROVIDER.manifest

    assert manifest.provider_key == "google_analytics"
    assert manifest.display_name == "Google Analytics"
    assert manifest.auth_modes == ("oauth", "service_account")
    assert manifest.owner_scope == "workspace"
    assert manifest.oauth_scopes == ("openid", "email", ANALYTICS_READONLY_SCOPE)
    assert manifest.resource_types == ("google_analytics_property",)
    assert manifest.requires_discovery is True
    assert manifest.capability_flags == frozenset({"read"})
    assert manifest.event_delivery == "none"
    assert {definition.name for definition in PROVIDER.tool_definitions} == {
        "google_analytics_check_report_fields",
        "google_analytics_list_report_fields",
        "google_analytics_run_realtime_report",
        "google_analytics_run_report",
    }
    assert "google_analytics" in GOOGLE_PROVIDER_KEYS
    assert "google_analytics" in VALID_TOOL_ICONS
    _validate_plugin(PROVIDER, expected_key="google_analytics")


def test_tool_foundation_declares_property_binding_and_presentation() -> None:
    assert GOOGLE_ANALYTICS_BINDING.provider_keys == frozenset({"google_analytics"})
    assert GOOGLE_ANALYTICS_BINDING.resource_types == frozenset({"google_analytics_property"})
    assert RESULTS_FIELD[0].label == "Properties"
