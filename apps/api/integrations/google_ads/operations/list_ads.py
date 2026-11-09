# apps/api/integrations/google_ads/operations/list_ads.py

"""List Google Ads ads for entity lookup."""

from collections.abc import Mapping, Sequence
from typing import Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import entity_id_boundary_filter, escape_gaql_like_literal, stream_rows

MAX_AD_LOOKUP = 101


async def list_ads(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    ad_ids: Sequence[str] = (),
    ad_group_ids: Sequence[str] = (),
    search: str | None = None,
    minimum_id: int | None = None,
    minimum_id_inclusive: bool = False,
    limit: int,
) -> list[Mapping[str, Any]]:
    """Returns non-removed ads in ad ID order; `search` matches the ad group name.

    Most responsive search ads have no name, so the operator finds them by ad group.
    """
    normalized_customer_id = normalize_customer_id(customer_id)
    if limit < 1 or limit > MAX_AD_LOOKUP:
        raise ValueError("Google Ads ad lookup limit must be between 1 and 101")
    normalized_ad_ids = sorted(set(ad_ids))
    normalized_ad_group_ids = sorted(set(ad_group_ids))
    if any(not value.isdigit() for value in (*normalized_ad_ids, *normalized_ad_group_ids)):
        raise ValueError("Google Ads ad ids must contain only digits")
    if len(normalized_ad_ids) > MAX_AD_LOOKUP or len(normalized_ad_group_ids) > MAX_AD_LOOKUP:
        raise ValueError("Google Ads ad lookup accepts at most 101 ids")
    filters = ["ad_group_ad.status != 'REMOVED'"]
    if normalized_ad_ids:
        filters.append(f"ad_group_ad.ad.id IN ({', '.join(normalized_ad_ids)})")
    if normalized_ad_group_ids:
        filters.append(f"ad_group.id IN ({', '.join(normalized_ad_group_ids)})")
    if search and search.strip():
        filters.append(f"ad_group.name LIKE '%{escape_gaql_like_literal(search.strip())}%'")
    if boundary_filter := entity_id_boundary_filter(
        "ad_group_ad.ad.id", minimum_id=minimum_id, inclusive=minimum_id_inclusive
    ):
        filters.append(boundary_filter)
    query = (
        "SELECT ad_group_ad.resource_name, ad_group_ad.status, ad_group_ad.ad.id, "  # noqa: S608 -- digit-only ids and escaped search
        "ad_group_ad.ad.name, ad_group_ad.ad.type, "
        "ad_group_ad.ad.responsive_search_ad.headlines, ad_group.id, ad_group.name, "
        "campaign.id, campaign.name FROM ad_group_ad "
        f"WHERE {' AND '.join(filters)} "
        f"ORDER BY ad_group_ad.ad.id LIMIT {limit}"
    )
    payload = await client.post(
        f"customers/{normalized_customer_id}/googleAds:searchStream",
        operation="list_ads",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={"query": query},
    )
    return [row for row in stream_rows(payload, max_rows=limit) if isinstance(row, Mapping)]


def ad_display_name(ad: Mapping[str, Any]) -> str:
    """Names an ad by its own name, else its first headline, else its ID."""
    name = str(ad.get("name") or "").strip()
    if name:
        return name
    responsive = ad.get("responsiveSearchAd")
    headlines = responsive.get("headlines") if isinstance(responsive, Mapping) else None
    if isinstance(headlines, list):
        for headline in headlines:
            text = headline.get("text") if isinstance(headline, Mapping) else None
            if isinstance(text, str) and text.strip():
                return text.strip()
    return f"Ad {ad.get('id', '')}".strip()
