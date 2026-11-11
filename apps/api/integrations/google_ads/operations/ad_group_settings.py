# apps/api/integrations/google_ads/operations/ad_group_settings.py

"""Reads ad group settings that `google_ads_update_ad_groups` changes, in card and API terms."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .campaign_bidding import AdGroupBid, ad_group_bids_used, bidding_values, micros, money, ratio
from .campaign_settings import api_value as campaign_api_value, card_value as campaign_card_value
from .utils import stream_rows

type AdGroupSetting = Literal[
    "name",
    "cpc_bid",
    "target_cpa",
    "target_roas",
    "final_url_suffix",
    "tracking_template",
    "custom_parameters",
    "ad_rotation",
]

# Each setting's field path in Google's JSON names, as the edit seam compares and masks it.
SETTING_PATHS: dict[AdGroupSetting, str] = {
    "name": "name",
    "cpc_bid": "cpcBidMicros",
    "target_cpa": "targetCpaMicros",
    "target_roas": "targetRoas",
    "final_url_suffix": "finalUrlSuffix",
    "tracking_template": "trackingUrlTemplate",
    "custom_parameters": "urlCustomParameters",
    "ad_rotation": "adRotationMode",
}
# Read-only paths a bid change is approved against but never sends, so a campaign strategy
# or target changed since approval, which can stop Google using the bid, is refused.
CAMPAIGN_BIDDING_GUARDS = (
    "campaign.biddingStrategyType",
    "campaign.biddingStrategy",
    "campaign.maximizeConversions.targetCpaMicros",
    "campaign.maximizeConversionValue.targetRoas",
)
_URL_SETTINGS = frozenset({"final_url_suffix", "tracking_template", "custom_parameters"})
_ROTATIONS = frozenset({"OPTIMIZE", "ROTATE_FOREVER"})
_FIELDS = (
    "ad_group.resource_name",
    "ad_group.id",
    "ad_group.name",
    "ad_group.status",
    "ad_group.cpc_bid_micros",
    "ad_group.target_cpa_micros",
    "ad_group.target_roas",
    "ad_group.final_url_suffix",
    "ad_group.tracking_url_template",
    "ad_group.url_custom_parameters",
    "ad_group.ad_rotation_mode",
    "campaign.name",
    "campaign.status",
    "campaign.bidding_strategy_type",
    "campaign.bidding_strategy",
    "campaign.maximize_conversions.target_cpa_micros",
    "campaign.maximize_conversion_value.target_roas",
)


def api_value(setting: AdGroupSetting, value: Any) -> Any:
    """Converts a setting from card terms to the value Google stores at its path; null clears it."""
    if setting in {"cpc_bid", "target_cpa"}:
        return micros(value) if value else None
    if setting in _URL_SETTINGS:
        return campaign_api_value(setting, value)
    return value


def card_value(setting: AdGroupSetting, value: Any) -> Any:
    """Converts a value Google stores to card terms: money as a decimal string, none as null."""
    if setting in {"cpc_bid", "target_cpa"}:
        return money(value)
    if setting == "target_roas":
        return ratio(value)
    if setting in _URL_SETTINGS:
        return campaign_card_value(setting, value)
    if setting == "ad_rotation":
        return value if value in _ROTATIONS else None
    return value if isinstance(value, str) and value else None


@dataclass(frozen=True, slots=True)
class LiveAdGroupSettings:
    resource_name: str
    ad_group_id: str
    status: str
    campaign_name: str
    campaign_status: str
    # Google's `bidding_strategy_type`, for a standard or a portfolio strategy.
    strategy_type: str
    portfolio: bool
    # The ad group bid fields Google uses under the campaign's bidding.
    bids_used: frozenset[AdGroupBid]
    # By setting path, as Google returned them, with absent fields as null or empty, plus the
    # campaign's bidding guards.
    values: Mapping[str, Any]

    def settings(self) -> dict[AdGroupSetting, Any]:
        return card_settings(self.values)


def card_settings(values: Mapping[str, Any]) -> dict[AdGroupSetting, Any]:
    """Every setting in card terms, from the values `read_ad_group_settings` returns."""
    return {
        setting: card_value(setting, values.get(path)) for setting, path in SETTING_PATHS.items()
    }


async def read_ad_group_settings(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    ad_group_ids: Sequence[str],
) -> dict[str, LiveAdGroupSettings]:
    """Returns each ad group's settings and its campaign's bidding by resource name.

    Removed ad groups are included; ad groups Google doesn't return are left out.
    """
    if not ad_group_ids or not all(item.isdigit() for item in ad_group_ids):
        raise ValueError("Google Ads ad group settings reads need ad group IDs")
    ids = ", ".join(sorted(set(ad_group_ids)))
    query = f"SELECT {', '.join(_FIELDS)} FROM ad_group WHERE ad_group.id IN ({ids})"  # noqa: S608 -- digits only
    payload = await client.post(
        f"customers/{normalize_customer_id(customer_id)}/googleAds:searchStream",
        operation="read_ad_group_settings",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={"query": query},
    )
    live: dict[str, LiveAdGroupSettings] = {}
    for row in stream_rows(payload, max_rows=len(set(ad_group_ids))):
        ad_group, campaign = row.get("adGroup"), row.get("campaign")
        if not isinstance(ad_group, Mapping) or not isinstance(campaign, Mapping):
            continue
        name, status = ad_group.get("resourceName"), ad_group.get("status")
        if not isinstance(name, str) or not isinstance(status, str):
            continue
        bidding = bidding_values(campaign)
        strategy_type = str(bidding["biddingStrategyType"] or "")
        portfolio = bidding["biddingStrategy"] is not None
        live[name] = LiveAdGroupSettings(
            resource_name=name,
            ad_group_id=str(ad_group.get("id", "")),
            status=status,
            campaign_name=str(campaign.get("name") or "Campaign"),
            campaign_status=str(campaign.get("status") or ""),
            strategy_type=strategy_type,
            portfolio=portfolio,
            bids_used=ad_group_bids_used(
                strategy_type,
                portfolio=portfolio,
                has_target_cpa=bidding["maximizeConversions.targetCpaMicros"] is not None,
                has_target_roas=bidding["maximizeConversionValue.targetRoas"] is not None,
            ),
            values={
                **_values(ad_group),
                **{
                    path: bidding[path.removeprefix("campaign.")]
                    for path in CAMPAIGN_BIDDING_GUARDS
                },
            },
        )
    return live


def _values(ad_group: Mapping[str, Any]) -> dict[str, Any]:
    """Each setting path's live value, normalised so equal settings compare equal."""
    return {
        path: api_value(setting, card_value(setting, ad_group.get(path)))
        for setting, path in SETTING_PATHS.items()
    }
