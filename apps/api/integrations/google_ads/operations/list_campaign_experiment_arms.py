# apps/api/integrations/google_ads/operations/list_campaign_experiment_arms.py

"""List active Google Ads experiment control arms for selected campaigns."""

from collections.abc import Mapping, Sequence
from typing import Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import stream_rows

MAX_ACTIVE_EXPERIMENT_ARMS = 100


async def list_active_campaign_experiment_arms(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    campaign_ids: Sequence[str],
) -> list[Mapping[str, Any]]:
    """Return a bounded control-arm lookup for initiated or enabled experiments."""
    normalized_customer_id = normalize_customer_id(customer_id)
    normalized_ids = sorted(set(campaign_ids))
    if not normalized_ids or len(normalized_ids) > 50:
        raise ValueError("Google Ads experiment lookup accepts between 1 and 50 campaign ids")
    if any(not campaign_id.isdigit() for campaign_id in normalized_ids):
        raise ValueError("Google Ads campaign ids must contain only digits")

    campaign_resources = [
        f"'customers/{normalized_customer_id}/campaigns/{campaign_id}'"
        for campaign_id in normalized_ids
    ]
    result_limit = MAX_ACTIVE_EXPERIMENT_ARMS + 1
    query = (
        "SELECT experiment_arm.campaigns, experiment_arm.control, "  # noqa: S608 -- resource names contain only normalized digit ids
        "experiment.status FROM experiment_arm "
        "WHERE experiment_arm.control = TRUE "
        "AND experiment.status IN ('INITIATED', 'ENABLED') "
        "AND experiment_arm.campaigns CONTAINS ANY "
        f"({', '.join(campaign_resources)}) LIMIT {result_limit}"
    )
    payload = await client.post(
        f"customers/{normalized_customer_id}/googleAds:searchStream",
        operation="list_active_campaign_experiment_arms",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={"query": query},
    )
    return list(stream_rows(payload, max_rows=result_limit))
