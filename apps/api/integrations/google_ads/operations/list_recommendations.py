# apps/api/integrations/google_ads/operations/list_recommendations.py

"""List Google Ads recommendations for selection and live verification."""

from collections.abc import Mapping, Sequence
from typing import Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from ..tools.utils.recommendation_utils import recommendation_customer_id
from .utils import stream_rows


async def list_recommendations(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    resource_names: Sequence[str] = (),
    include_dismissed: bool,
    limit: int,
) -> list[Mapping[str, Any]]:
    """Return a bounded set of recommendation mappings."""
    normalized_customer_id = normalize_customer_id(customer_id)
    if limit < 1 or limit > 10_000:
        raise ValueError("Google Ads recommendation lookup limit must be between 1 and 10,000")

    normalized_names = tuple(sorted(set(resource_names)))
    if len(normalized_names) > 100:
        raise ValueError("Google Ads recommendation lookup accepts at most 100 references")
    for resource_name in normalized_names:
        if recommendation_customer_id(resource_name) != normalized_customer_id:
            raise ValueError("Google Ads recommendation resource name is invalid for this account")

    filters: list[str] = []
    if normalized_names:
        quoted = ", ".join(f"'{resource_name}'" for resource_name in normalized_names)
        filters.append(f"recommendation.resource_name IN ({quoted})")
    if not include_dismissed:
        filters.append("recommendation.dismissed = FALSE")
    where_clause = f" WHERE {' AND '.join(filters)}" if filters else ""
    query = (
        "SELECT campaign.name, recommendation.resource_name, recommendation.type, "  # noqa: S608 -- validated resource names and bounded integers
        "recommendation.dismissed, recommendation.campaign, recommendation.campaigns, "
        "recommendation.impact FROM recommendation"
        f"{where_clause} LIMIT {limit}"
    )
    payload = await client.post(
        f"customers/{normalized_customer_id}/googleAds:searchStream",
        operation="list_recommendations",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={"query": query},
    )
    recommendations = []
    for row in stream_rows(payload, max_rows=limit):
        recommendation = row.get("recommendation")
        if not isinstance(recommendation, Mapping):
            continue
        normalized = dict(recommendation)
        campaign = row.get("campaign")
        if isinstance(campaign, Mapping) and isinstance(campaign.get("name"), str):
            normalized["affectedCampaignLabel"] = campaign["name"][:500]
        recommendations.append(normalized)
    return recommendations
