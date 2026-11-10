# apps/api/integrations/google_ads/operations/keyword_settings.py

"""Reads keyword settings that `google_ads_update_keywords` changes, in card and API terms."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .campaign_bidding import AdGroupBid, ad_group_bids_used, bidding_values, micros, money
from .campaign_settings import api_value as campaign_api_value, card_value as campaign_card_value
from .utils import stream_rows

type KeywordSetting = Literal[
    "match_type",
    "cpc_bid",
    "final_urls",
    "final_mobile_urls",
    "final_url_suffix",
    "tracking_template",
    "custom_parameters",
]

# Each setting's field path in Google's JSON names, as the edit seam compares and masks it.
SETTING_PATHS: dict[KeywordSetting, str] = {
    "match_type": "keyword.matchType",
    "cpc_bid": "cpcBidMicros",
    "final_urls": "finalUrls",
    "final_mobile_urls": "finalMobileUrls",
    "final_url_suffix": "finalUrlSuffix",
    "tracking_template": "trackingUrlTemplate",
    "custom_parameters": "urlCustomParameters",
}
# The settings a new keyword takes from the one it replaces when its match type changes.
CARRIED_SETTINGS: tuple[KeywordSetting, ...] = tuple(
    setting for setting in SETTING_PATHS if setting != "match_type"
)
# Read-only paths a bid change is approved against but never sends, so a campaign strategy
# changed since approval, which can stop Google using the bid, is refused.
CAMPAIGN_BIDDING_GUARDS = ("campaign.biddingStrategyType", "campaign.biddingStrategy")
_URL_LISTS = frozenset({"final_urls", "final_mobile_urls"})
_URL_SETTINGS = frozenset({"final_url_suffix", "tracking_template", "custom_parameters"})
_MATCH_TYPES = frozenset({"EXACT", "PHRASE", "BROAD"})
# At most 500 quoted resource names keep the query well inside Google's length limit.
_MAX_READ = 500
_FIELDS = (
    "ad_group_criterion.resource_name",
    "ad_group_criterion.status",
    "ad_group_criterion.type",
    "ad_group_criterion.negative",
    "ad_group_criterion.keyword.text",
    "ad_group_criterion.keyword.match_type",
    "ad_group_criterion.cpc_bid_micros",
    "ad_group_criterion.final_urls",
    "ad_group_criterion.final_mobile_urls",
    "ad_group_criterion.final_url_suffix",
    "ad_group_criterion.tracking_url_template",
    "ad_group_criterion.url_custom_parameters",
    "ad_group.resource_name",
    "ad_group.name",
    "ad_group.status",
    "campaign.name",
    "campaign.status",
    "campaign.bidding_strategy_type",
    "campaign.bidding_strategy",
    "campaign.maximize_conversions.target_cpa_micros",
    "campaign.maximize_conversion_value.target_roas",
)


def api_value(setting: KeywordSetting, value: Any) -> Any:
    """Converts a setting from card terms to the value Google stores at its path; null clears it."""
    if setting == "cpc_bid":
        return micros(value) if value else None
    if setting in _URL_LISTS:
        return list(value or ())
    if setting in _URL_SETTINGS:
        return campaign_api_value(setting, value)
    return value


def card_value(setting: KeywordSetting, value: Any) -> Any:
    """Converts a value Google stores to card terms: money as a decimal string, lists never null."""
    if setting == "cpc_bid":
        return money(value)
    if setting in _URL_LISTS:
        return [item for item in value or () if isinstance(item, str)]
    if setting in _URL_SETTINGS:
        return campaign_card_value(setting, value)
    return value if value in _MATCH_TYPES else None


def card_settings(values: Mapping[str, Any]) -> dict[KeywordSetting, Any]:
    """Every setting in card terms, from the values `read_keyword_settings` returns."""
    return {
        setting: card_value(setting, values.get(path)) for setting, path in SETTING_PATHS.items()
    }


@dataclass(frozen=True, slots=True)
class LiveKeyword:
    resource_name: str
    text: str
    status: str
    ad_group: str
    ad_group_name: str
    ad_group_status: str
    campaign_name: str
    campaign_status: str
    # Google's `bidding_strategy_type`, for a standard or a portfolio strategy.
    strategy_type: str
    portfolio: bool
    # The ad group bid fields Google uses; a keyword's own CPC bid follows the same rule.
    bids_used: frozenset[AdGroupBid]
    # By setting path, as Google returned them, with absent fields as null or empty, plus the
    # status and the campaign's bidding guards.
    values: Mapping[str, Any]

    def settings(self) -> dict[KeywordSetting, Any]:
        return card_settings(self.values)


async def read_keyword_settings(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    resource_names: Sequence[str],
) -> dict[str, LiveKeyword]:
    """Returns each positive keyword's settings and its campaign's bidding by resource name.

    Removed keywords are included; criteria Google doesn't return, or that aren't positive
    keywords, are left out.
    """
    prefix = f"customers/{normalize_customer_id(customer_id)}/adGroupCriteria/"
    wanted = set(resource_names)
    if (
        not wanted
        or len(wanted) > _MAX_READ
        or not all(
            name.startswith(prefix)
            and name[len(prefix) :].count("~") == 1
            and name[len(prefix) :].replace("~", "").isdigit()
            for name in wanted
        )
    ):
        raise ValueError("Google Ads keyword settings reads need this account's keywords")
    names = ", ".join(f"'{name}'" for name in sorted(wanted))
    query = (
        f"SELECT {', '.join(_FIELDS)} FROM ad_group_criterion "  # noqa: S608 -- validated names
        f"WHERE ad_group_criterion.resource_name IN ({names})"
    )
    payload = await client.post(
        f"customers/{normalize_customer_id(customer_id)}/googleAds:searchStream",
        operation="read_keyword_settings",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={"query": query},
    )
    live: dict[str, LiveKeyword] = {}
    for row in stream_rows(payload, max_rows=len(wanted)):
        keyword = _live_keyword(row)
        if keyword is not None and keyword.resource_name in wanted:
            live[keyword.resource_name] = keyword
    return live


def _live_keyword(row: Mapping[str, Any]) -> LiveKeyword | None:
    criterion, ad_group, campaign = (
        row.get("adGroupCriterion"),
        row.get("adGroup"),
        row.get("campaign"),
    )
    if not all(isinstance(item, Mapping) for item in (criterion, ad_group, campaign)):
        return None
    keyword = criterion.get("keyword")
    name, status = criterion.get("resourceName"), criterion.get("status")
    if (
        criterion.get("type") != "KEYWORD"
        or criterion.get("negative") is True
        or not isinstance(keyword, Mapping)
        or not isinstance(name, str)
        or not isinstance(status, str)
    ):
        return None
    bidding = bidding_values(campaign)
    strategy_type = str(bidding["biddingStrategyType"] or "")
    portfolio = bidding["biddingStrategy"] is not None
    return LiveKeyword(
        resource_name=name,
        text=str(keyword.get("text") or ""),
        status=status,
        ad_group=str(ad_group.get("resourceName") or ""),
        ad_group_name=str(ad_group.get("name") or "Ad group"),
        ad_group_status=str(ad_group.get("status") or ""),
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
            **_values(criterion),
            "status": status,
            "campaign.biddingStrategyType": bidding["biddingStrategyType"],
            "campaign.biddingStrategy": bidding["biddingStrategy"],
        },
    )


def _values(criterion: Mapping[str, Any]) -> dict[str, Any]:
    """Each setting path's live value, normalised so equal settings compare equal."""
    values: dict[str, Any] = {}
    for setting, path in SETTING_PATHS.items():
        raw: Any = criterion
        for part in path.split("."):
            raw = raw.get(part) if isinstance(raw, Mapping) else None
        values[path] = api_value(setting, card_value(setting, raw))
    return values
