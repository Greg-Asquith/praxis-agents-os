# apps/api/integrations/google_ads/tools/utils/campaigns.py

"""Shared campaign-reference verification for Google Ads write tools."""

from collections.abc import Mapping, Sequence

from pydantic_ai import ModelRetry

from integrations.google_ads.client import GoogleAdsClient
from integrations.google_ads.operations.utils import stream_rows
from services.integrations.context.domain import ResolvedContextEntry

from .routing import login_customer_id


async def verify_campaigns(
    client: GoogleAdsClient,
    *,
    entry: ResolvedContextEntry,
    campaign_ids: Sequence[str],
    ignore_removed: bool,
) -> None:
    """Fail closed unless every approved campaign still exists in its account."""
    status_filter = "AND campaign.status != 'REMOVED' " if ignore_removed else ""
    query = (
        "SELECT campaign.id, campaign.name, campaign.status FROM campaign "  # noqa: S608 -- callers provide digit-only ids
        f"WHERE campaign.id IN ({', '.join(campaign_ids)}) "
        f"{status_filter}"
        f"LIMIT {len(campaign_ids)}"
    )
    payload = await client.post(
        f"customers/{entry.external_id}/googleAds:searchStream",
        operation="resolve_campaign_references",
        login_customer_id=login_customer_id(entry),
        json={"query": query},
    )
    resolved_ids = {
        str(campaign.get("id", ""))
        for row in stream_rows(payload)
        if isinstance((campaign := row.get("campaign")), Mapping)
        and (not ignore_removed or campaign.get("status") != "REMOVED")
    }
    if resolved_ids != set(campaign_ids):
        raise ModelRetry(
            "A selected Google Ads campaign is unavailable. Ask the user to choose it again."
        )
