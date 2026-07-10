# apps/api/services/integrations/manifest.py

"""Integration provider manifest contract and singular registry."""

import re
from dataclasses import dataclass
from typing import Literal

AUTH_MODES = frozenset({"oauth", "api_key", "service_account", "system_token"})
PROVIDER_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class IntegrationProviderManifest:
    provider_key: str
    display_name: str
    auth_modes: tuple[str, ...]
    owner_scope: Literal["user", "workspace"]
    oauth_scopes: tuple[str, ...] = ()
    resource_types: tuple[str, ...] = ()
    requires_discovery: bool = False
    required_form_fields: tuple[str, ...] = ()
    capability_flags: frozenset[str] = frozenset()
    event_delivery: Literal["none", "webhook", "pubsub_push"] = "none"


PROVIDER_MANIFESTS: dict[str, IntegrationProviderManifest] = {}


def register_provider_manifest(manifest: IntegrationProviderManifest) -> None:
    _validate_manifest(manifest)
    if manifest.provider_key in PROVIDER_MANIFESTS:
        raise RuntimeError(f"Duplicate integration provider key: {manifest.provider_key}")
    PROVIDER_MANIFESTS[manifest.provider_key] = manifest


def _validate_manifest(manifest: IntegrationProviderManifest) -> None:
    if not PROVIDER_KEY_PATTERN.fullmatch(manifest.provider_key):
        raise RuntimeError("Integration provider key must be lowercase snake_case")
    if not manifest.display_name.strip():
        raise RuntimeError("Integration provider display name must not be blank")
    if not manifest.auth_modes or not set(manifest.auth_modes).issubset(AUTH_MODES):
        raise RuntimeError("Integration provider has unsupported auth modes")
    if "oauth" in manifest.auth_modes and not manifest.oauth_scopes:
        raise RuntimeError("OAuth integration providers must declare scopes")
    if "api_key" in manifest.auth_modes and not manifest.required_form_fields:
        raise RuntimeError("API-key integration providers must declare form fields")
    if manifest.requires_discovery and not manifest.resource_types:
        raise RuntimeError("Discoverable integration providers must declare resource types")
