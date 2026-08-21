# apps/api/integrations/google_ads/tools/verifiers/campaign.py

"""Live entity-reference verification for Google Ads write tools."""

from collections.abc import Sequence

from pydantic_ai import ModelRetry

from integrations.google_ads.client import GoogleAdsClient
from integrations.google_ads.operations.list_campaign_device_criteria import (
    GoogleAdsCampaignDeviceState,
    list_campaign_device_criteria,
)
from integrations.google_ads.operations.list_campaigns import list_campaigns
from integrations.google_ads.tools.utils.routing import login_customer_id
from services.integrations.context.domain import ResolvedContextEntry

from .utils import validated_ids


async def verify_campaigns(
    client: GoogleAdsClient,
    *,
    entry: ResolvedContextEntry,
    campaign_ids: Sequence[str],
    ignore_removed: bool,
) -> None:
    """Fail closed unless every approved campaign still exists in its account."""
    normalized_ids = validated_ids(
        campaign_ids,
        invalid_message=(
            "A selected Google Ads campaign is unavailable. Ask the user to choose it again."
        ),
    )
    campaigns = await list_campaigns(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        campaign_ids=normalized_ids,
        limit=len(normalized_ids),
        exclude_removed=ignore_removed,
    )
    resolved_ids = {
        str(campaign.get("id", ""))
        for campaign in campaigns
        if not ignore_removed or campaign.get("status") != "REMOVED"
    }
    if resolved_ids != set(normalized_ids):
        raise ModelRetry(
            "A selected Google Ads campaign is unavailable. Ask the user to choose it again."
        )


async def verify_campaigns_for_device_bidding(
    client: GoogleAdsClient,
    *,
    entry: ResolvedContextEntry,
    campaign_ids: Sequence[str],
) -> dict[str, GoogleAdsCampaignDeviceState]:
    """Returns device state after verifying every selected campaign exists."""
    normalized_ids = validated_ids(
        campaign_ids,
        invalid_message=(
            "A selected Google Ads campaign is unavailable. Ask the user to choose it again."
        ),
    )
    states = await list_campaign_device_criteria(
        client,
        customer_id=entry.external_id,
        login_customer_id=login_customer_id(entry),
        campaign_ids=normalized_ids,
    )
    if set(states) != set(normalized_ids):
        raise ModelRetry(
            "A selected Google Ads campaign is unavailable. Ask the user to choose it again."
        )
    return states
