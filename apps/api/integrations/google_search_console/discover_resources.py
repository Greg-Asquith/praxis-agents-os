# apps/api/integrations/google_search_console/discover_resources.py

"""Discover Google Search Console properties visible to one credential."""

from core.exceptions.integration import IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.plugin import DiscoveredIntegrationResource

from .client import GoogleSearchConsoleClient, normalize_site_url

WEBMASTERS_SCOPE = "https://www.googleapis.com/auth/webmasters"
INDEXING_SCOPE = "https://www.googleapis.com/auth/indexing"
_WRITE_PERMISSION_LEVELS = frozenset({"siteOwner"})


async def discover_resources(
    credential_value: str,
    _principal_label: str | None = None,
) -> tuple[DiscoveredIntegrationResource, ...]:
    async def access_token(_force: bool) -> str:
        return credential_value

    return await discover_google_search_console_sites(GoogleSearchConsoleClient(access_token))


async def discover_google_search_console_sites(
    client: GoogleSearchConsoleClient,
) -> tuple[DiscoveredIntegrationResource, ...]:
    payload = await client.webmasters_get(
        "sites",
        operation="list_sites",
        policy=IntegrationRequestPolicy.READ,
    )
    if not isinstance(payload, dict):
        raise _invalid_sites_response()
    site_entries = payload.get("siteEntry", [])
    if not isinstance(site_entries, list):
        raise _invalid_sites_response()

    resources: dict[str, DiscoveredIntegrationResource] = {}
    sort_keys: dict[str, tuple[str, str]] = {}
    for item in site_entries:
        if not isinstance(item, dict):
            continue
        permission_level = str(item.get("permissionLevel", "")).strip()
        if permission_level == "siteUnverifiedUser":
            continue
        try:
            external_id = normalize_site_url(str(item.get("siteUrl", "")))
        except IntegrationValidationError:
            continue
        if external_id in resources:
            continue
        property_type, display_name = _site_presentation(external_id)
        writable = permission_level in _WRITE_PERMISSION_LEVELS
        resources[external_id] = DiscoveredIntegrationResource(
            resource_type="google_search_console_site",
            external_id=external_id,
            display_name=display_name,
            parent_external_id=None,
            writable=writable,
            required_write_scopes=(WEBMASTERS_SCOPE,) if writable else (),
            permissions_metadata={
                "permission_level": permission_level,
                "property_type": property_type,
            },
        )
        sort_keys[external_id] = (property_type, display_name.casefold())
    return tuple(resources[key] for key in sorted(resources, key=sort_keys.__getitem__))


def _site_presentation(site_url: str) -> tuple[str, str]:
    if site_url.startswith("sc-domain:"):
        domain = site_url.removeprefix("sc-domain:")
        return "domain", f"{domain}"
    return "url_prefix", site_url


def _invalid_sites_response() -> IntegrationValidationError:
    return IntegrationValidationError(
        "Google Search Console returned an invalid sites response",
        provider_key="google_search_console",
        operation="list_sites",
    )
