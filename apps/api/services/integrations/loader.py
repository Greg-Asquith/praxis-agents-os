# apps/api/services/integrations/loader.py

"""Load explicitly enabled integration-provider packages at process boot."""

import importlib

from core.settings import settings
from services.integrations.manifest import register_provider_manifest
from services.integrations.plugin import IntegrationProviderPlugin


def load_enabled_providers() -> None:
    """Import and register every provider named by the single boot allowlist."""
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
    if plugin.tool_definitions:
        from services.agents.runtime.tools.contract import validate_definition

    for definition in plugin.tool_definitions:
        validate_definition(definition)
        if definition.provider != expected_key:
            raise RuntimeError("Integration tool provider must match its package")
        if not definition.name.startswith(f"{expected_key}_"):
            raise RuntimeError("Integration tool name must be prefixed by its provider key")
