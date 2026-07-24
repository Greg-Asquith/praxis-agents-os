# apps/api/services/integrations/loader.py

"""Load explicitly enabled integration-provider packages at process boot."""

import importlib
import re

from core.settings import settings
from services.integrations.manifest import register_provider_manifest
from services.integrations.plugin import IntegrationProviderPlugin, register_provider_plugin

PREVIEW_KIND_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def load_enabled_providers() -> None:
    """Import and register every provider named by the single boot allowlist."""
    oauth_client_owners: dict[str, str] = {}
    for key in settings.INTEGRATIONS_ENABLED_PROVIDERS:
        try:
            module = importlib.import_module(f"integrations.{key}")
        except ModuleNotFoundError as exc:
            if exc.name == f"integrations.{key}":
                raise RuntimeError(f"Unknown enabled integration provider: {key}") from exc
            raise
        plugin = getattr(module, "PROVIDER", None)
        if not isinstance(plugin, IntegrationProviderPlugin):
            raise TypeError(f"Integration provider package '{key}' has no valid PROVIDER")
        _validate_plugin(plugin, expected_key=key)
        if plugin.oauth_config is not None:
            client_id = plugin.oauth_config().client_id.strip()
            previous_owner = oauth_client_owners.get(client_id) if client_id else None
            if previous_owner is not None:
                raise RuntimeError(
                    "OAuth integration providers must use isolated client IDs: "
                    f"{previous_owner} and {key} share one"
                )
            if client_id:
                oauth_client_owners[client_id] = key
        register_provider_plugin(plugin)
        register_provider_manifest(plugin.manifest)

        if plugin.tool_definitions:
            from services.agents.runtime.tools.registry import register_tool_definition

            for definition in plugin.tool_definitions:
                register_tool_definition(definition)


def _validate_plugin(plugin: IntegrationProviderPlugin, *, expected_key: str) -> None:
    manifest = plugin.manifest
    if manifest.provider_key != expected_key:
        raise RuntimeError(
            f"Integration provider key mismatch: package={expected_key}, "
            f"manifest={manifest.provider_key}"
        )
    if manifest.requires_discovery and plugin.discover_resources is None:
        raise RuntimeError(
            f"Discoverable integration provider '{expected_key}' must implement discovery"
        )
    if "oauth" in manifest.auth_modes and plugin.oauth_config is None:
        raise RuntimeError(
            f"OAuth integration provider '{expected_key}' must own its OAuth configuration"
        )
    if plugin.event_definition is not None and manifest.event_delivery == "none":
        raise RuntimeError(
            f"Integration provider '{expected_key}' contributes events but declares no delivery"
        )
    for definition in plugin.tool_definitions:
        if definition.provider != expected_key:
            raise RuntimeError("Integration tool provider must match its package")
        if not definition.name.startswith(f"{expected_key}_"):
            raise RuntimeError("Integration tool name must be prefixed by its provider key")
    preview_kinds: set[str] = set()
    for definition in plugin.preview_definitions:
        if not PREVIEW_KIND_PATTERN.fullmatch(definition.kind):
            raise RuntimeError("Integration preview kind must be lowercase snake_case")
        if definition.kind in preview_kinds:
            raise RuntimeError(
                f"Duplicate integration preview kind for provider '{expected_key}': "
                f"{definition.kind}"
            )
        if not definition.operation.strip():
            raise RuntimeError("Integration preview operation must not be blank")
        preview_kinds.add(definition.kind)
