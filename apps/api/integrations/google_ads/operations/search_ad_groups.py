# apps/api/integrations/google_ads/operations/search_ad_groups.py

"""Compiles new Search ad groups for the build seam and reads what their campaign allows."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleAdsClient, normalize_customer_id
from .assets import link_new_asset
from .build import CampaignBuild
from .campaign_bidding import AdGroupBid, ad_group_bids_used
from .responsive_search_ads import ad_group_ad_body
from .utils import stream_rows

if TYPE_CHECKING:
    from ..tools.schemas.ad_groups import GoogleAdsNewAdGroup, GoogleAdsNewKeyword

type AdGroupItemKind = Literal[
    "ad_group", "keyword", "negative_keyword", "ad", "asset", "asset_link"
]

# Enough for the card to check names as they're edited; Google refuses any clash past this.
_MAX_NAMES_READ = 2_000


@dataclass(frozen=True, slots=True)
class AdGroupItem:
    """Which ad group in the request a build step came from, and which of its items it is."""

    ad_group: int
    kind: AdGroupItemKind
    position: int = 0


@dataclass(frozen=True, slots=True)
class SearchCampaignFacts:
    """A live campaign's channel and bidding, and the names of its live ad groups."""

    name: str
    channel: str
    strategy: str
    portfolio: bool
    has_target_cpa: bool
    has_target_roas: bool
    ad_group_names: tuple[str, ...]

    @property
    def bids_used(self) -> frozenset[AdGroupBid]:
        return ad_group_bids_used(
            self.strategy,
            portfolio=self.portfolio,
            has_target_cpa=self.has_target_cpa,
            has_target_roas=self.has_target_roas,
        )

    @property
    def accepts_cpc_bid(self) -> bool:
        return "cpc_bid" in self.bids_used

    @property
    def accepts_target_cpa(self) -> bool:
        return "target_cpa" in self.bids_used

    @property
    def accepts_target_roas(self) -> bool:
        return "target_roas" in self.bids_used


def add_search_ad_group(
    build: CampaignBuild,
    ad_group: "GoogleAdsNewAdGroup",
    *,
    index: int,
    campaign: str,
    status: str,
) -> None:
    """Adds one ad group with its keywords, negative keywords, ads, and assets to the build."""
    body: dict[str, Any] = {
        "name": ad_group.name,
        "status": status,
        "type": "SEARCH_STANDARD",
        "campaign": campaign,
    }
    if ad_group.cpc_bid_micros is not None:
        body["cpcBidMicros"] = str(ad_group.cpc_bid_micros)
    if ad_group.target_cpa_micros is not None:
        body["targetCpaMicros"] = str(ad_group.target_cpa_micros)
    if ad_group.target_roas is not None:
        body["targetRoas"] = ad_group.target_roas
    name = build.create("adGroup", body, label=ad_group.name, source=AdGroupItem(index, "ad_group"))
    if name is None:
        raise ValueError("Google Ads builds must name new ad groups")
    for position, keyword in enumerate(ad_group.keywords):
        build.create(
            "adGroupCriterion",
            _keyword_body(keyword, ad_group=name),
            label=keyword.text,
            source=AdGroupItem(index, "keyword", position),
        )
    for position, negative in enumerate(ad_group.negative_keywords):
        build.create(
            "adGroupCriterion",
            {
                "adGroup": name,
                "negative": True,
                "keyword": {"text": negative.text, "matchType": negative.match_type},
            },
            label=negative.text,
            source=AdGroupItem(index, "negative_keyword", position),
        )
    for position, ad in enumerate(ad_group.ads):
        build.create(
            "adGroupAd",
            ad_group_ad_body(ad, ad_group=name, status=status),
            label=f"{ad_group.name} · Ad {position + 1}",
            source=AdGroupItem(index, "ad", position),
        )
    for position, asset in enumerate(ad_group.assets):
        link_new_asset(
            build,
            asset,
            link="adGroupAsset",
            owner=name,
            asset_source=AdGroupItem(index, "asset", position),
            link_source=AdGroupItem(index, "asset_link", position),
        )


def _keyword_body(keyword: "GoogleAdsNewKeyword", *, ad_group: str) -> dict[str, Any]:
    body: dict[str, Any] = {
        "adGroup": ad_group,
        "status": "ENABLED",
        "keyword": {"text": keyword.text, "matchType": keyword.match_type},
    }
    if keyword.cpc_bid_micros is not None:
        body["cpcBidMicros"] = str(keyword.cpc_bid_micros)
    if keyword.final_url:
        body["finalUrls"] = [keyword.final_url]
    return body


async def read_search_campaign(
    client: GoogleAdsClient,
    *,
    customer_id: str,
    login_customer_id: str,
    campaign_id: str,
) -> SearchCampaignFacts | None:
    """Returns the campaign's facts, or None when it's removed or doesn't exist."""
    if not campaign_id.isdigit():
        raise ValueError("Google Ads campaign ids must contain only digits")
    path = f"customers/{normalize_customer_id(customer_id)}/googleAds:searchStream"
    campaigns = await client.post(
        path,
        operation="read_search_campaign",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={
            "query": (
                "SELECT campaign.id, campaign.name, campaign.advertising_channel_type, "  # noqa: S608 -- digit-only id
                "campaign.bidding_strategy_type, campaign.bidding_strategy, "
                "campaign.maximize_conversions.target_cpa_micros, "
                "campaign.maximize_conversion_value.target_roas FROM campaign "
                f"WHERE campaign.id = {campaign_id} AND campaign.status != 'REMOVED'"
            )
        },
    )
    rows = stream_rows(campaigns, max_rows=1)
    campaign = rows[0].get("campaign") if rows else None
    if not isinstance(campaign, Mapping):
        return None
    names = await client.post(
        path,
        operation="read_search_campaign",
        policy=IntegrationRequestPolicy.READ,
        login_customer_id=login_customer_id,
        json={
            "query": (
                "SELECT ad_group.id, ad_group.name FROM ad_group "  # noqa: S608 -- digit-only id
                f"WHERE campaign.id = {campaign_id} AND ad_group.status != 'REMOVED' "
                f"ORDER BY ad_group.id LIMIT {_MAX_NAMES_READ}"
            )
        },
    )
    return SearchCampaignFacts(
        name=str(campaign.get("name") or f"Campaign {campaign_id}"),
        channel=str(campaign.get("advertisingChannelType") or ""),
        strategy=str(campaign.get("biddingStrategyType") or ""),
        portfolio=bool(campaign.get("biddingStrategy")),
        has_target_cpa=_is_set(campaign, "maximizeConversions", "targetCpaMicros"),
        has_target_roas=_is_set(campaign, "maximizeConversionValue", "targetRoas"),
        ad_group_names=tuple(
            str(row["adGroup"]["name"])
            for row in stream_rows(names, max_rows=_MAX_NAMES_READ)
            if isinstance(row.get("adGroup"), Mapping) and row["adGroup"].get("name")
        ),
    )


def _is_set(campaign: Mapping[str, Any], strategy: str, target: str) -> bool:
    fields = campaign.get(strategy)
    if not isinstance(fields, Mapping):
        return False
    try:
        return float(fields.get(target) or 0) > 0
    except (TypeError, ValueError):
        return False
