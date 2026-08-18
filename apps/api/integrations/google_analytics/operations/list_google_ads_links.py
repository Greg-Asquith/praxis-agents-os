# apps/api/integrations/google_analytics/operations/list_google_ads_links.py

"""List Google Ads links for one Google Analytics property."""

from typing import Any

from core.exceptions.integration import IntegrationValidationError

from ..client import GoogleAnalyticsClient

GOOGLE_ADS_LINK_PAGE_SIZE = 200
GOOGLE_ADS_LINK_MAX_PAGES = 5


async def list_google_ads_links(
    client: GoogleAnalyticsClient,
    *,
    property_id: str,
) -> dict[str, Any]:
    raw_links = await client.admin_get_paged(
        f"properties/{property_id}/googleAdsLinks",
        items_key="googleAdsLinks",
        page_size=GOOGLE_ADS_LINK_PAGE_SIZE,
        max_pages=GOOGLE_ADS_LINK_MAX_PAGES,
    )
    links = [_google_ads_link(item) for item in raw_links]
    return {"links": links, "link_count": len(links)}


def _google_ads_link(value: dict[str, Any]) -> dict[str, Any]:
    customer_id = _customer_id(value.get("customerId"))
    created_at = str(value.get("createTime") or "").strip()[:64] or None
    return {
        "customer_id": customer_id,
        "can_manage_clients": value.get("canManageClients") is True,
        "ads_personalization_enabled": value.get("adsPersonalizationEnabled") is True,
        "created_at": created_at,
    }


def _customer_id(value: Any) -> str:
    raw = str(value or "").strip()
    normalized = raw.replace("-", "").replace(" ", "")
    if not normalized.isdigit() or len(normalized) > 32:
        raise IntegrationValidationError(
            "Google Analytics returned an invalid Google Ads customer id",
            provider_key="google_analytics",
            operation="list_google_ads_links",
        )
    return normalized
