# apps/api/integrations/google_ads/operations/keyword_additions.py

"""Reads the ad groups `google_ads_create_keywords` adds keywords to, with their bidding."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .campaign_bidding import ad_group_bids_used, bidding_values, money
from .utils import stream_rows

_MAX_AD_GROUPS = 100
_FIELDS = (
    "ad_group.resource_name",
    "ad_group.name",
    "ad_group.status",
    "ad_group.type",
    "ad_group.cpc_bid_micros",
    "campaign.name",
    "campaign.status",
    "campaign.advertising_channel_type",
    "campaign.bidding_strategy_type",
    "campaign.bidding_strategy",
    "campaign.maximize_conversions.target_cpa_micros",
    "campaign.maximize_conversion_value.target_roas",
)


@dataclass(frozen=True, slots=True)
class LiveAdGroup:
    resource_name: str
    name: str
    status: str
    type: str
    campaign_name: str
    campaign_status: str
    channel: str
    # Google's `bidding_strategy_type`, for a standard or a portfolio strategy.
    strategy_type: str
    portfolio: bool
    # Whether Google uses a keyword's own max CPC under the campaign's bidding.
    uses_cpc_bid: bool
    # The ad group's default max CPC as a decimal string, when Google uses it.
    default_bid: str | None


async def read_keyword_ad_groups(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    ad_group_ids: Sequence[str],
) -> dict[str, LiveAdGroup]:
    """Returns each ad group, removed ones included, by resource name, in one query."""
    wanted = sorted(set(ad_group_ids))
    if not wanted or len(wanted) > _MAX_AD_GROUPS or not all(item.isdigit() for item in wanted):
        raise ValueError("Google Ads ad group reads need digit ids, at most 100")
    customer = normalize_customer_id(customer_id)
    query = (
        f"SELECT {', '.join(_FIELDS)} FROM ad_group "  # noqa: S608 -- digit-only ids
        f"WHERE ad_group.id IN ({', '.join(wanted)})"
    )
    payload = await client.post(
        f"customers/{customer}/googleAds:searchStream",
        operation="read_keyword_ad_groups",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={"query": query},
    )
    live: dict[str, LiveAdGroup] = {}
    for row in stream_rows(payload, max_rows=len(wanted)):
        ad_group = _live_ad_group(row)
        if ad_group is not None:
            live[ad_group.resource_name] = ad_group
    return live


def _live_ad_group(row: Mapping[str, Any]) -> LiveAdGroup | None:
    ad_group, campaign = row.get("adGroup"), row.get("campaign")
    if not isinstance(ad_group, Mapping) or not isinstance(campaign, Mapping):
        return None
    name = ad_group.get("resourceName")
    if not isinstance(name, str):
        return None
    bidding = bidding_values(campaign)
    strategy_type = str(bidding["biddingStrategyType"] or "")
    portfolio = bidding["biddingStrategy"] is not None
    bids_used = ad_group_bids_used(
        strategy_type,
        portfolio=portfolio,
        has_target_cpa=bidding["maximizeConversions.targetCpaMicros"] is not None,
        has_target_roas=bidding["maximizeConversionValue.targetRoas"] is not None,
    )
    return LiveAdGroup(
        resource_name=name,
        name=str(ad_group.get("name") or "Ad group"),
        status=str(ad_group.get("status") or ""),
        type=str(ad_group.get("type") or ""),
        campaign_name=str(campaign.get("name") or "Campaign"),
        campaign_status=str(campaign.get("status") or ""),
        channel=str(campaign.get("advertisingChannelType") or ""),
        strategy_type=strategy_type,
        portfolio=portfolio,
        uses_cpc_bid="cpc_bid" in bids_used,
        default_bid=money(ad_group.get("cpcBidMicros")) if "cpc_bid" in bids_used else None,
    )
