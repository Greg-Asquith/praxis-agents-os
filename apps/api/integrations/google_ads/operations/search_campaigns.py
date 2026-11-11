# apps/api/integrations/google_ads/operations/search_campaigns.py

"""Compiles a new Search campaign, with its budget and campaign criteria, for the build seam."""

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any, Literal

from .assets import link_new_asset
from .build import CampaignBuild
from .search_ad_groups import SearchCampaignFacts

if TYPE_CHECKING:
    from ..tools.schemas.campaigns import GoogleAdsNewSearchCampaign

type CampaignItemKind = Literal[
    "budget", "campaign", "location", "excluded_location", "negative_keyword", "asset", "asset_link"
]

# Google's bidding strategy type for each strategy the card offers.
_STRATEGY_TYPES = {
    "MANUAL_CPC": "MANUAL_CPC",
    "MAXIMIZE_CLICKS": "TARGET_SPEND",
    "MAXIMIZE_CONVERSIONS": "MAXIMIZE_CONVERSIONS",
    "MAXIMIZE_CONVERSION_VALUE": "MAXIMIZE_CONVERSION_VALUE",
    "TARGET_IMPRESSION_SHARE": "TARGET_IMPRESSION_SHARE",
}


@dataclass(frozen=True, slots=True)
class CampaignItem:
    """Which of the campaign's own objects a build step came from."""

    kind: CampaignItemKind
    position: int = 0


def new_campaign_facts(campaign: "GoogleAdsNewSearchCampaign") -> SearchCampaignFacts:
    """Describes the new campaign's bidding as a live one's, so ad group bids follow one rule."""
    bidding = campaign.bidding
    return SearchCampaignFacts(
        name=campaign.name,
        channel="SEARCH",
        strategy=_STRATEGY_TYPES[bidding.strategy],
        portfolio=False,
        has_target_cpa=bool(getattr(bidding, "target_cpa", None)),
        has_target_roas=getattr(bidding, "target_roas", None) is not None,
        ad_group_names=(),
    )


def add_search_campaign(
    build: CampaignBuild,
    campaign: "GoogleAdsNewSearchCampaign",
    *,
    status: str,
    today: date,
) -> str:
    """Adds the budget, campaign, locations, negative keywords, and assets; returns its name.

    Args:
        today: The date in the account time zone. A start on or before it starts the campaign
            when it's turned on, because Google refuses a start time in the past.
    """
    budget = campaign.budget
    if budget.kind == "new":
        budget_name = build.create(
            "campaignBudget",
            {
                "name": campaign.name,
                "amountMicros": str(budget.amount_micros),
                "deliveryMethod": "STANDARD",
                "explicitlyShared": False,
                "period": "DAILY",
            },
            label=campaign.name,
            source=CampaignItem("budget"),
        )
    else:
        budget_name = (
            f"customers/{budget.budget.customer_id}/campaignBudgets/{budget.budget.budget_id}"
        )
    body: dict[str, Any] = {
        "name": campaign.name,
        "status": status,
        "advertisingChannelType": "SEARCH",
        "campaignBudget": budget_name,
        "networkSettings": {
            "targetGoogleSearch": True,
            "targetSearchNetwork": campaign.search_partners,
            "targetContentNetwork": campaign.display_expansion,
            "targetPartnerSearchNetwork": False,
        },
        "geoTargetTypeSetting": {"positiveGeoTargetType": campaign.location_setting},
        "containsEuPoliticalAdvertising": (
            "CONTAINS_EU_POLITICAL_ADVERTISING"
            if campaign.contains_eu_political_advertising
            else "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING"
        ),
        **_bidding(campaign),
    }
    if campaign.start_date and campaign.start_date > today:
        body["startDateTime"] = f"{campaign.start_date.isoformat()} 00:00:00"
    if campaign.end_date:
        body["endDateTime"] = f"{campaign.end_date.isoformat()} 23:59:59"
    name = build.create("campaign", body, label=campaign.name, source=CampaignItem("campaign"))
    if name is None:
        raise ValueError("Google Ads builds must name new campaigns")
    for kind, locations in (
        ("location", campaign.locations),
        ("excluded_location", campaign.excluded_locations),
    ):
        for position, location in enumerate(locations):
            criterion: dict[str, Any] = {
                "campaign": name,
                "location": {"geoTargetConstant": f"geoTargetConstants/{location.key}"},
            }
            if kind == "excluded_location":
                criterion["negative"] = True
            build.create(
                "campaignCriterion",
                criterion,
                label=location.name or location.key,
                source=CampaignItem(kind, position),
            )
    for position, negative in enumerate(campaign.negative_keywords):
        build.create(
            "campaignCriterion",
            {
                "campaign": name,
                "negative": True,
                "keyword": {"text": negative.text, "matchType": negative.match_type},
            },
            label=negative.text,
            source=CampaignItem("negative_keyword", position),
        )
    for position, asset in enumerate(campaign.assets):
        link_new_asset(
            build,
            asset,
            link="campaignAsset",
            owner=name,
            asset_source=CampaignItem("asset", position),
            link_source=CampaignItem("asset_link", position),
        )
    return name


def _bidding(campaign: "GoogleAdsNewSearchCampaign") -> dict[str, Any]:
    """The campaign's bidding field; each strategy sets only its own oneof member."""
    bidding = campaign.bidding
    if bidding.strategy == "MANUAL_CPC":
        return {"manualCpc": {}}
    if bidding.strategy == "MAXIMIZE_CLICKS":
        ceiling = bidding.max_cpc_micros
        return {"targetSpend": {"cpcBidCeilingMicros": str(ceiling)} if ceiling else {}}
    if bidding.strategy == "MAXIMIZE_CONVERSIONS":
        target = bidding.target_cpa_micros
        return {"maximizeConversions": {"targetCpaMicros": str(target)} if target else {}}
    if bidding.strategy == "MAXIMIZE_CONVERSION_VALUE":
        roas = {"targetRoas": bidding.target_roas} if bidding.target_roas is not None else {}
        return {"maximizeConversionValue": roas}
    return {
        "targetImpressionShare": {
            "location": bidding.location,
            "locationFractionMicros": str(bidding.share_percent * 10_000),
            "cpcBidCeilingMicros": str(bidding.max_cpc_micros),
        }
    }
