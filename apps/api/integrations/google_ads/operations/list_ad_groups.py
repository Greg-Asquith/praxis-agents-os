# apps/api/integrations/google_ads/operations/list_ad_groups.py

"""List Google Ads ad groups for entity lookup and live verification."""

from collections.abc import Mapping, Sequence
from typing import Any

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import escape_gaql_like_literal, stream_rows


async def list_ad_groups(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    ad_group_ids: Sequence[str] = (),
    search: str | None = None,
    limit: int,
    exclude_removed: bool,
) -> list[Mapping[str, Any]]:
    """Return validated ad-group rows in stable provider order."""
    normalized_customer_id = normalize_customer_id(customer_id)
    if limit < 1 or limit > 101:
        raise ValueError("Google Ads ad-group lookup limit must be between 1 and 101")
    if any(not ad_group_id.isdigit() for ad_group_id in ad_group_ids):
        raise ValueError("Google Ads ad-group ids must contain only digits")

    normalized_ids = sorted(set(ad_group_ids))
    if len(normalized_ids) > 101:
        raise ValueError("Google Ads ad-group lookup accepts at most 101 ids")
    filters = []
    if exclude_removed:
        filters.append("ad_group.status != 'REMOVED'")
    if normalized_ids:
        filters.append(f"ad_group.id IN ({', '.join(normalized_ids)})")
    if search and search.strip():
        filters.append(f"ad_group.name LIKE '%{escape_gaql_like_literal(search.strip())}%'")
    where_clause = f" WHERE {' AND '.join(filters)}" if filters else ""
    query = (
        "SELECT ad_group.id, ad_group.name, ad_group.status, campaign.name "  # noqa: S608 -- digit-only ids and escaped search
        f"FROM ad_group{where_clause} "
        f"ORDER BY ad_group.name, ad_group.id LIMIT {limit}"
    )
    payload = await client.post(
        f"customers/{normalized_customer_id}/googleAds:searchStream",
        operation="list_ad_groups",
        login_customer_id=login_customer_id,
        json={"query": query},
    )
    return [row for row in stream_rows(payload) if isinstance(row, Mapping)]
