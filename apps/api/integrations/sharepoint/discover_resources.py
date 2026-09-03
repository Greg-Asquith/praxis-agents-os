# apps/api/integrations/sharepoint/discover_resources.py

"""Discover OneDrive and SharePoint document libraries for one delegated grant."""

import logging
from typing import Any
from urllib.parse import quote

import httpx2

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationError,
    IntegrationNotFoundError,
)
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.microsoft_graph import (
    MicrosoftGraphClient,
    fixed_access_token,
    graph_string,
    required_graph_string,
)
from services.integrations.plugin import (
    DiscoveredIntegrationResource,
    IntegrationDiscoveryResult,
)

from .settings import sharepoint_settings

logger = logging.getLogger(__name__)

_MAX_PAGES = 20
_MAX_DRIVES_PER_SITE = 200


async def discover_resources(
    access_token: str,
    _principal_label: str | None = None,
    pacing_key: str = "",
) -> tuple[DiscoveredIntegrationResource, ...] | IntegrationDiscoveryResult:
    async with httpx2.AsyncClient() as http_client:
        client = MicrosoftGraphClient(
            fixed_access_token(access_token),
            provider_key="sharepoint",
            client=http_client,
            pacing_key=pacing_key,
        )
        return await _discover_resources(client)


async def _discover_resources(
    client: MicrosoftGraphClient,
) -> tuple[DiscoveredIntegrationResource, ...] | IntegrationDiscoveryResult:
    resources: dict[str, DiscoveredIntegrationResource] = {}
    onedrive, degraded_reason = await _discover_onedrive(client)
    if onedrive is not None:
        resources[onedrive.external_id] = onedrive

    max_sites = sharepoint_settings.SHAREPOINT_DISCOVERY_MAX_SITES
    sites, site_limit_reached = await _discover_sites(client, max_sites=max_sites)
    if site_limit_reached:
        degraded_reason = "sharepoint_site_limit_reached"
    site_resources, failed_site_ids = await _discover_site_drives(client, sites)
    if failed_site_ids:
        degraded_reason = "sharepoint_site_discovery_partial"
    for resource in site_resources:
        resources.setdefault(resource.external_id, resource)

    discovered = tuple(resources.values())
    if degraded_reason is not None:
        return IntegrationDiscoveryResult(
            resources=discovered,
            degraded_reason=degraded_reason,
            preserved_parent_external_ids=frozenset(failed_site_ids),
        )
    return discovered


async def _discover_onedrive(
    client: MicrosoftGraphClient,
) -> tuple[DiscoveredIntegrationResource | None, str | None]:
    try:
        drive = await client.get(
            "/me/drive",
            operation="discover_onedrive",
            policy=IntegrationRequestPolicy.READ,
            params={"$select": "id,name,driveType,webUrl"},
        )
    except IntegrationNotFoundError:
        return None, "onedrive_unavailable"
    required_graph_string(drive, "id", provider_key="sharepoint")
    return _drive_resource(drive, site=None, followed=False, personal=True), None


async def _discover_site_drives(
    client: MicrosoftGraphClient,
    sites: list[tuple[dict[str, Any], bool]],
) -> tuple[list[DiscoveredIntegrationResource], set[str]]:
    resources: list[DiscoveredIntegrationResource] = []
    failed_site_ids: set[str] = set()
    for site, followed in sites:
        site_id = graph_string(site, "id")
        if not site_id:
            continue
        try:
            drives = await client.paginate(
                f"/sites/{quote(site_id, safe=',')}/drives",
                operation="discover_sharepoint_drives",
                params={"$select": "id,name,driveType,webUrl"},
                max_items=_MAX_DRIVES_PER_SITE,
                max_pages=_MAX_PAGES,
            )
        except IntegrationAuthError:
            raise
        except IntegrationError:
            logger.warning(
                "Skipping a SharePoint site whose document libraries could not be listed",
                extra={"site_id": site_id},
            )
            failed_site_ids.add(site_id)
            continue
        for drive in drives:
            resource = _drive_resource(drive, site=site, followed=followed, personal=False)
            if resource is not None:
                resources.append(resource)
    return resources, failed_site_ids


async def _discover_sites(
    client: MicrosoftGraphClient,
    *,
    max_sites: int,
) -> tuple[list[tuple[dict[str, Any], bool]], bool]:
    followed_sites = await client.paginate(
        "/me/followedSites",
        operation="discover_followed_sharepoint_sites",
        params={"$select": "id,displayName,webUrl"},
        max_items=max_sites,
        max_pages=_MAX_PAGES,
    )
    ordered: list[tuple[dict[str, Any], bool]] = []
    seen: set[str] = set()
    _append_distinct_sites(ordered, seen, followed_sites, followed=True, max_sites=max_sites)
    if len(ordered) >= max_sites:
        return ordered, True

    searched_sites = await client.paginate(
        "/sites",
        operation="discover_accessible_sharepoint_sites",
        params={"search": "*", "$select": "id,displayName,webUrl"},
        max_items=max_sites + len(seen),
        max_pages=_MAX_PAGES,
    )
    truncated = _append_distinct_sites(
        ordered,
        seen,
        searched_sites,
        followed=False,
        max_sites=max_sites,
    )
    return ordered, truncated or len(ordered) >= max_sites


def _append_distinct_sites(
    target: list[tuple[dict[str, Any], bool]],
    seen: set[str],
    candidates: list[dict[str, Any]],
    *,
    followed: bool,
    max_sites: int,
) -> bool:
    for site in candidates:
        site_id = graph_string(site, "id")
        if not site_id or site_id in seen:
            continue
        if len(target) >= max_sites:
            return True
        seen.add(site_id)
        target.append((site, followed))
    return False


def _drive_resource(
    drive: object,
    *,
    site: dict[str, Any] | None,
    followed: bool,
    personal: bool,
) -> DiscoveredIntegrationResource | None:
    if not isinstance(drive, dict):
        return None
    drive_id = graph_string(drive, "id")
    drive_name = graph_string(drive, "name")
    if not drive_id:
        return None
    site_id = graph_string(site, "id") if site is not None else ""
    site_name = graph_string(site, "displayName") if site is not None else ""
    display_name = (
        "OneDrive" if personal else f"{site_name or 'SharePoint'} › {drive_name or 'Documents'}"  # noqa: RUF001
    )
    metadata: dict[str, object] = {
        "followed": followed,
    }
    metadata.update(
        {
            key: value
            for key, value in (
                ("drive_type", graph_string(drive, "driveType")),
                ("site_id", site_id),
                ("site_name", site_name),
                ("web_url", graph_string(drive, "webUrl")),
            )
            if value
        }
    )
    return DiscoveredIntegrationResource(
        resource_type="sharepoint_drive",
        external_id=drive_id,
        display_name=display_name,
        parent_external_id=site_id or None,
        writable=False,
        permissions_metadata=metadata,
    )
