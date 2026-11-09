# apps/api/integrations/google_ads/operations/list_bidding_strategies.py

"""List an account's own portfolio bidding strategies for lookup and approval checks."""

from collections.abc import Mapping, Sequence
from typing import Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import entity_id_boundary_filter, escape_gaql_like_literal, stream_rows

MAX_BIDDING_STRATEGY_LOOKUP = 101


async def list_bidding_strategies(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    bidding_strategy_ids: Sequence[str] = (),
    search: str | None = None,
    minimum_id: int | None = None,
    minimum_id_inclusive: bool = False,
    limit: int,
    exclude_removed: bool = True,
) -> list[Mapping[str, Any]]:
    """Returns `biddingStrategy` objects in ID order, with id, name, type, status, and campaign count.

    Strategies a manager account owns and shares aren't listed. `exclude_removed` (on by
    default) leaves out removed strategies, which campaigns can't use.
    """
    if limit < 1 or limit > MAX_BIDDING_STRATEGY_LOOKUP:
        raise ValueError("Google Ads bidding strategy lookup limit must be between 1 and 101")
    normalized_ids = sorted(set(bidding_strategy_ids))
    if any(not value.isdigit() for value in normalized_ids):
        raise ValueError("Google Ads bidding strategy ids must contain only digits")
    if len(normalized_ids) > MAX_BIDDING_STRATEGY_LOOKUP:
        raise ValueError("Google Ads bidding strategy lookup accepts at most 101 ids")
    filters = ["bidding_strategy.status != 'REMOVED'"] if exclude_removed else []
    if normalized_ids:
        filters.append(f"bidding_strategy.id IN ({', '.join(normalized_ids)})")
    if search and search.strip():
        filters.append(f"bidding_strategy.name LIKE '%{escape_gaql_like_literal(search.strip())}%'")
    if boundary_filter := entity_id_boundary_filter(
        "bidding_strategy.id", minimum_id=minimum_id, inclusive=minimum_id_inclusive
    ):
        filters.append(boundary_filter)
    where_clause = f"WHERE {' AND '.join(filters)} " if filters else ""
    query = (
        "SELECT bidding_strategy.id, bidding_strategy.name, bidding_strategy.type, "  # noqa: S608 -- digit-only ids and escaped search
        "bidding_strategy.status, bidding_strategy.campaign_count FROM bidding_strategy "
        f"{where_clause}ORDER BY bidding_strategy.id LIMIT {limit}"
    )
    payload = await client.post(
        f"customers/{normalize_customer_id(customer_id)}/googleAds:searchStream",
        operation="list_bidding_strategies",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={"query": query},
    )
    return [
        strategy
        for row in stream_rows(payload, max_rows=limit)
        if isinstance((strategy := row.get("biddingStrategy")), Mapping)
    ]
