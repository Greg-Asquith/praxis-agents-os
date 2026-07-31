# apps/api/services/integrations/loader.py

"""Load explicitly enabled integration-provider packages at process boot."""

import importlib
import re

from core.settings import settings
from services.integrations.manifest import register_provider_manifest
from services.integrations.plugin import IntegrationProviderPlugin, register_provider_plugin
from services.jobs.domain import is_valid_job_kind
from services.jobs.registry import get_job_handler

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

        if plugin.entity_resolvers:
            from services.agents.runtime.entity_references.registry import register_entity_resolver

            for resolver in plugin.entity_resolvers:
                register_entity_resolver(resolver)

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
    if plugin.metadata_sync_job_kind is not None:
        if not is_valid_job_kind(plugin.metadata_sync_job_kind):
            raise RuntimeError(
                f"Integration provider '{expected_key}' declares an invalid metadata sync job kind"
            )
        if get_job_handler(plugin.metadata_sync_job_kind) is None:
            raise RuntimeError(
                f"Integration provider '{expected_key}' metadata sync handler is not registered"
            )
    for definition in plugin.tool_definitions:
        if definition.provider != expected_key:
            raise RuntimeError("Integration tool provider must match its package")
        if not definition.name.startswith(f"{expected_key}_"):
            raise RuntimeError("Integration tool name must be prefixed by its provider key")
    resolver_kinds: set[str] = set()
    for resolver in plugin.entity_resolvers:
        from services.agents.runtime.entity_references.domain import ScopedEntityReference

        if resolver.provider_key != expected_key:
            raise RuntimeError("Integration entity resolver provider must match its package")
        if not issubclass(resolver.reference_type, ScopedEntityReference):
            raise TypeError(
                "Integration entity resolvers require scoped structured reference types"
            )
        if resolver.entity_kind in resolver_kinds:
            raise RuntimeError(
                f"Duplicate integration entity resolver kind for provider '{expected_key}': "
                f"{resolver.entity_kind}"
            )
        resolver_kinds.add(resolver.entity_kind)
    declared_entity_kinds = {
        field.entity_kind
        for definition in plugin.tool_definitions
        for field in definition.presentation.arg_fields
        if field.entity_kind is not None
    }
    undeclared_resolvers = resolver_kinds.difference(declared_entity_kinds)
    if undeclared_resolvers:
        raise RuntimeError(
            "Integration provider contributes entity resolvers not declared by its tools: "
            f"{', '.join(sorted(undeclared_resolvers))}"
        )
    missing_resolvers = declared_entity_kinds.difference(resolver_kinds)
    if missing_resolvers:
        raise RuntimeError(
            "Integration provider tool entity fields require provider-owned resolvers: "
            f"{', '.join(sorted(missing_resolvers))}"
        )
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
