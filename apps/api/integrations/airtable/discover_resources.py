# apps/api/integrations/airtable/discover_resources.py

"""Discover bases visible to an Airtable personal access token."""

from typing import Any

from services.integrations.http import IntegrationRequestPolicy
from services.integrations.plugin import DiscoveredIntegrationResource

from .client import AirtableClient

_WRITABLE_PERMISSION_LEVELS = frozenset({"create", "edit"})


async def discover_resources(access_token: str, _principal_label: str | None = None):
    async def resolve_token() -> str:
        return access_token

    client = AirtableClient(resolve_token)
    resources: list[DiscoveredIntegrationResource] = []
    offset: str | None = None
    seen_offsets: set[str] = set()
    while True:
        params = {"offset": offset} if offset else None
        payload = await client.get(
            "meta/bases",
            operation="discover_bases",
            policy=IntegrationRequestPolicy.READ,
            params=params,
        )
        bases = payload.get("bases") if isinstance(payload, dict) else None
        if isinstance(bases, list):
            resources.extend(_resource(item) for item in bases if isinstance(item, dict))
        next_offset = str(payload.get("offset", "")).strip() if isinstance(payload, dict) else ""
        if not next_offset or next_offset in seen_offsets:
            break
        seen_offsets.add(next_offset)
        offset = next_offset
    return tuple(resources)


def _resource(payload: dict[str, Any]) -> DiscoveredIntegrationResource:
    permission_level = str(payload.get("permissionLevel", "")).strip().lower()
    return DiscoveredIntegrationResource(
        resource_type="airtable_base",
        external_id=str(payload.get("id", "")).strip(),
        display_name=str(payload.get("name", "")).strip(),
        writable=permission_level in _WRITABLE_PERMISSION_LEVELS,
        permissions_metadata={"permission_level": permission_level or "unknown"},
    )
