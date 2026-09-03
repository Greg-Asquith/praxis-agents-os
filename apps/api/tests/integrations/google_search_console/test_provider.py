# apps/api/tests/integrations/google_search_console/test_provider.py

"""Google Search Console provider manifest contracts."""

from integrations.google_search_console import PROVIDER
from integrations.google_search_console.discover_resources import WEBMASTERS_SCOPE
from integrations.google_search_console.tools.utils.bindings import (
    GOOGLE_SEARCH_CONSOLE_BINDING,
    GOOGLE_SEARCH_CONSOLE_WRITE_BINDING,
    RESULTS_FIELD,
)
from services.agents.runtime.tools.contract import VALID_TOOL_ICONS
from services.integrations.loader import _validate_plugin


def test_manifest_declares_workspace_site_provider_with_slice_a_tools() -> None:
    manifest = PROVIDER.manifest

    assert manifest.provider_key == "google_search_console"
    assert manifest.display_name == "Google Search Console"
    assert manifest.auth_modes == ("oauth",)
    assert manifest.owner_scope == "workspace"
    assert manifest.oauth_scopes == ("openid", "email", WEBMASTERS_SCOPE)
    assert manifest.resource_types == ("google_search_console_site",)
    assert manifest.requires_discovery is True
    assert manifest.capability_flags == frozenset({"read", "write"})
    assert manifest.event_delivery == "none"
    assert {definition.name for definition in PROVIDER.tool_definitions} == {
        "google_search_console_list_sitemaps",
        "google_search_console_query_search_analytics",
    }
    assert PROVIDER.oauth_config().protocol.identity_source == "google_userinfo"
    assert "google_search_console" in VALID_TOOL_ICONS
    _validate_plugin(PROVIDER, expected_key="google_search_console")


def test_tool_foundation_declares_read_and_write_site_bindings() -> None:
    assert GOOGLE_SEARCH_CONSOLE_BINDING.provider_keys == frozenset({"google_search_console"})
    assert GOOGLE_SEARCH_CONSOLE_BINDING.resource_types == frozenset({"google_search_console_site"})
    assert GOOGLE_SEARCH_CONSOLE_BINDING.requires_write is False
    assert GOOGLE_SEARCH_CONSOLE_WRITE_BINDING.requires_write is True
    assert RESULTS_FIELD[0].label == "Sites"
