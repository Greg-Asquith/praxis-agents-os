# apps/api/integrations/google_ads/operations/list_campaigns.py

"""List Google Ads campaigns for entity lookup and live verification."""

from collections.abc import Mapping, Sequence
from typing import Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import entity_id_boundary_filter, escape_gaql_like_literal, stream_rows


async def list_campaigns(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    campaign_ids: Sequence[str] = (),
    search: str | None = None,
    minimum_id: int | None = None,
    minimum_id_inclusive: bool = False,
    limit: int,
    exclude_removed: bool,
) -> list[Mapping[str, Any]]:
    """Return validated campaign mappings in stable provider order."""
    normalized_customer_id = normalize_customer_id(customer_id)
    if limit < 1 or limit > 101:
        raise ValueError("Google Ads campaign lookup limit must be between 1 and 101")
    if any(not campaign_id.isdigit() for campaign_id in campaign_ids):
        raise ValueError("Google Ads campaign ids must contain only digits")

    normalized_ids = sorted(set(campaign_ids))
    if len(normalized_ids) > 101:
        raise ValueError("Google Ads campaign lookup accepts at most 101 ids")
    filters = []
    if exclude_removed:
        filters.append("campaign.status != 'REMOVED'")
    if normalized_ids:
        filters.append(f"campaign.id IN ({', '.join(normalized_ids)})")
    if search and search.strip():
        filters.append(f"campaign.name LIKE '%{escape_gaql_like_literal(search.strip())}%'")
    if boundary_filter := entity_id_boundary_filter(
        "campaign.id",
        minimum_id=minimum_id,
        inclusive=minimum_id_inclusive,
    ):
        filters.append(boundary_filter)
    where_clause = f" WHERE {' AND '.join(filters)}" if filters else ""
    query = (
        "SELECT campaign.id, campaign.name, campaign.status FROM campaign"  # noqa: S608 -- digit-only ids and escaped search
        f"{where_clause} "
        f"ORDER BY campaign.id LIMIT {limit}"
    )
    payload = await client.post(
        f"customers/{normalized_customer_id}/googleAds:searchStream",
        operation="list_campaigns",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={"query": query},
    )
    return [
        campaign
        for row in stream_rows(payload, max_rows=limit)
        if isinstance((campaign := row.get("campaign")), Mapping)
    ]
