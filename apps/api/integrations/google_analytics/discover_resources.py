# apps/api/integrations/google_analytics/discover_resources.py

"""Discover Google Analytics properties visible to one credential."""

from typing import Any

from core.exceptions.integration import IntegrationValidationError
from services.integrations.credentials import (
    GoogleServiceAccountTokenProvider,
    parse_google_service_account_json,
)
from services.integrations.plugin import DiscoveredIntegrationResource

from .client import GoogleAnalyticsClient, normalize_property_id

ANALYTICS_READONLY_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"


async def discover_resources(
    credential_value: str,
    _principal_label: str | None = None,
) -> tuple[DiscoveredIntegrationResource, ...]:
    if credential_value.lstrip().startswith("{"):
        credentials = parse_google_service_account_json(
            credential_value,
            provider_key="google_analytics",
        )
        token_provider = GoogleServiceAccountTokenProvider(
            credentials,
            provider_key="google_analytics",
            scope=ANALYTICS_READONLY_SCOPE,
        )
        access_token = token_provider.access_token
    else:

        async def access_token(_force: bool) -> str:
            return credential_value

    return await discover_google_analytics_properties(GoogleAnalyticsClient(access_token))


async def discover_google_analytics_properties(
    client: GoogleAnalyticsClient,
) -> tuple[DiscoveredIntegrationResource, ...]:
    accounts = await client.admin_get_paged(
        "accountSummaries",
        items_key="accountSummaries",
        page_size=200,
        max_pages=25,
    )
    resources: dict[str, DiscoveredIntegrationResource] = {}
    sort_keys: dict[str, tuple[str, str]] = {}
    for account in accounts:
        account_id = _terminal_id(account.get("account"), prefix="accounts/")
        account_name = str(account.get("displayName", "")).strip()
        properties = account.get("propertySummaries", [])
        if not isinstance(properties, list):
            continue
        for property_summary in properties:
            if not isinstance(property_summary, dict):
                continue
            resource_name = str(property_summary.get("property", "")).strip()
            try:
                property_id = normalize_property_id(resource_name)
            except IntegrationValidationError:
                continue
            if property_id in resources:
                continue
            display_name = str(property_summary.get("displayName", "")).strip() or property_id
            resources[property_id] = DiscoveredIntegrationResource(
                resource_type="google_analytics_property",
                external_id=property_id,
                display_name=display_name,
                parent_external_id=None,
                writable=False,
                permissions_metadata={
                    "account_id": account_id,
                    "account_display_name": account_name,
                    "property_type": str(property_summary.get("propertyType", "")).strip(),
                    "resource_name": resource_name,
                },
            )
            sort_keys[property_id] = (account_name.casefold(), display_name.casefold())
    return tuple(resources[key] for key in sorted(resources, key=sort_keys.__getitem__))


def _terminal_id(value: Any, *, prefix: str) -> str:
    normalized = str(value or "").strip()
    return normalized.removeprefix(prefix) if normalized.startswith(prefix) else normalized
