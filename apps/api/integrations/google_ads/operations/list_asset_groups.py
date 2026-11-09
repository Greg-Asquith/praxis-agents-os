# apps/api/integrations/google_ads/operations/list_asset_groups.py

"""List Google Ads asset groups for entity lookup."""

from collections.abc import Mapping, Sequence
from typing import Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import entity_id_boundary_filter, escape_gaql_like_literal, stream_rows

MAX_ASSET_GROUP_LOOKUP = 101


async def list_asset_groups(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    asset_group_ids: Sequence[str] = (),
    search: str | None = None,
    minimum_id: int | None = None,
    minimum_id_inclusive: bool = False,
    limit: int,
) -> list[Mapping[str, Any]]:
    """Returns non-removed asset groups in ID order."""
    normalized_customer_id = normalize_customer_id(customer_id)
    if limit < 1 or limit > MAX_ASSET_GROUP_LOOKUP:
        raise ValueError("Google Ads asset group lookup limit must be between 1 and 101")
    normalized_ids = sorted(set(asset_group_ids))
    if any(not value.isdigit() for value in normalized_ids):
        raise ValueError("Google Ads asset group ids must contain only digits")
    if len(normalized_ids) > MAX_ASSET_GROUP_LOOKUP:
        raise ValueError("Google Ads asset group lookup accepts at most 101 ids")
    filters = ["asset_group.status != 'REMOVED'"]
    if normalized_ids:
        filters.append(f"asset_group.id IN ({', '.join(normalized_ids)})")
    if search and search.strip():
        filters.append(f"asset_group.name LIKE '%{escape_gaql_like_literal(search.strip())}%'")
    if boundary_filter := entity_id_boundary_filter(
        "asset_group.id", minimum_id=minimum_id, inclusive=minimum_id_inclusive
    ):
        filters.append(boundary_filter)
    query = (
        "SELECT asset_group.id, asset_group.name, asset_group.status, "  # noqa: S608 -- digit-only ids and escaped search
        "campaign.id, campaign.name FROM asset_group "
        f"WHERE {' AND '.join(filters)} "
        f"ORDER BY asset_group.id LIMIT {limit}"
    )
    payload = await client.post(
        f"customers/{normalized_customer_id}/googleAds:searchStream",
        operation="list_asset_groups",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={"query": query},
    )
    return [row for row in stream_rows(payload, max_rows=limit) if isinstance(row, Mapping)]
