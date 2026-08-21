# apps/api/integrations/google_ads/operations/list_campaign_device_criteria.py

"""Read campaign bidding strategies and campaign-level device criteria."""

from collections.abc import Mapping, Sequence
from typing import TypedDict

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .utils import stream_rows


class GoogleAdsDeviceCriterionState(TypedDict):
    criterion_id: str
    bid_modifier: float


class GoogleAdsCampaignDeviceState(TypedDict):
    bidding_strategy_type: str
    target_cpa_configured: bool
    devices: dict[str, GoogleAdsDeviceCriterionState]


async def list_campaign_device_criteria(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    campaign_ids: Sequence[str],
) -> dict[str, GoogleAdsCampaignDeviceState]:
    """Returns bidding strategies and existing device criteria for campaigns."""
    normalized_customer_id = normalize_customer_id(customer_id)
    if any(not campaign_id.isdigit() for campaign_id in campaign_ids):
        raise ValueError("Google Ads campaign ids must contain only digits")
    normalized_ids = sorted(set(campaign_ids))
    if not normalized_ids:
        return {}
    if len(normalized_ids) > 50:
        raise ValueError("Google Ads device bidding accepts at most 50 campaign ids")

    id_filter = ", ".join(normalized_ids)
    campaign_query = (
        "SELECT campaign.id, campaign.status, campaign.bidding_strategy_type, "  # noqa: S608 -- digit-only campaign ids
        "campaign.maximize_conversions.target_cpa_micros, "
        "bidding_strategy.maximize_conversions.target_cpa_micros "
        "FROM campaign "
        f"WHERE campaign.status != 'REMOVED' AND campaign.id IN ({id_filter})"
    )
    campaign_payload = await client.post(
        f"customers/{normalized_customer_id}/googleAds:searchStream",
        operation="list_campaign_device_strategies",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={"query": campaign_query},
    )
    states: dict[str, GoogleAdsCampaignDeviceState] = {}
    for row in stream_rows(campaign_payload, max_rows=len(normalized_ids)):
        campaign = row.get("campaign")
        if not isinstance(campaign, Mapping):
            continue
        campaign_id = str(campaign.get("id", ""))
        strategy = campaign.get("biddingStrategyType")
        if campaign_id in normalized_ids and isinstance(strategy, str) and strategy:
            bidding_strategy = row.get("biddingStrategy")
            states[campaign_id] = {
                "bidding_strategy_type": strategy,
                "target_cpa_configured": (
                    _target_cpa_configured(campaign) or _target_cpa_configured(bidding_strategy)
                ),
                "devices": {},
            }

    criterion_query = (
        "SELECT campaign.id, campaign_criterion.criterion_id, "  # noqa: S608 -- digit-only campaign ids
        "campaign_criterion.device.type, campaign_criterion.bid_modifier, "
        "campaign_criterion.status "
        "FROM campaign_criterion "
        "WHERE campaign_criterion.type = 'DEVICE' "
        "AND campaign_criterion.status != 'REMOVED' "
        f"AND campaign.id IN ({id_filter})"
    )
    criterion_payload = await client.post(
        f"customers/{normalized_customer_id}/googleAds:searchStream",
        operation="list_campaign_device_criteria",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={"query": criterion_query},
    )
    for row in stream_rows(criterion_payload, max_rows=len(normalized_ids) * 10):
        campaign = row.get("campaign")
        criterion = row.get("campaignCriterion")
        if not isinstance(campaign, Mapping) or not isinstance(criterion, Mapping):
            continue
        campaign_id = str(campaign.get("id", ""))
        state = states.get(campaign_id)
        device = criterion.get("device")
        criterion_id = str(criterion.get("criterionId", ""))
        bid_modifier = criterion.get("bidModifier")
        criterion_status = criterion.get("status")
        device_type = device.get("type") if isinstance(device, Mapping) else None
        if (
            state is None
            or criterion_status == "REMOVED"
            or not isinstance(device_type, str)
            or not criterion_id.isdigit()
            or isinstance(bid_modifier, bool)
            or not isinstance(bid_modifier, int | float)
        ):
            continue
        state["devices"][device_type] = {
            "criterion_id": criterion_id,
            "bid_modifier": float(bid_modifier),
        }
    return states


def _target_cpa_configured(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    maximize_conversions = value.get("maximizeConversions")
    if not isinstance(maximize_conversions, Mapping):
        return False
    target_cpa_micros = maximize_conversions.get("targetCpaMicros")
    if isinstance(target_cpa_micros, bool):
        return False
    try:
        return int(target_cpa_micros) > 0
    except (TypeError, ValueError):
        return False
