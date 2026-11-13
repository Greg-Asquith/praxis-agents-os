# apps/api/integrations/google_ads/operations/search_campaigns.py

"""Compiles a new campaign's budget, settings, and locations, and a whole Search campaign."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any, Literal

from .assets import link_new_asset
from .build import CampaignBuild
from .search_ad_groups import SearchCampaignFacts
from .search_targeting import LocationOption

if TYPE_CHECKING:
    from ..tools.schemas.campaigns import GoogleAdsNewSearchCampaign, NewCampaign

type CampaignItemKind = Literal[
    "budget",
    "campaign",
    "location",
    "excluded_location",
    "negative_keyword",
    "asset",
    "asset_link",
    "language",
    "conversion_goal",
    "text_asset",
    "brand_link",
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


def asks_eu_political(campaign: "NewCampaign", locations: Mapping[str, LocationOption]) -> bool:
    """Checks whether the campaign must say if its ads are EU political ads.

    Google leaves the answer out only for a campaign whose targeted locations are all outside
    the EU. A location Google doesn't return counts as inside it.

    Args:
        locations: Google's locations by key, as `read_locations` returns them.
    """
    return (
        campaign.contains_eu_political_advertising
        or not campaign.locations
        or any(
            (option := locations.get(item.key)) is None or option.eu_political_declaration
            for item in campaign.locations
        )
    )


def add_search_campaign(
    build: CampaignBuild,
    campaign: "GoogleAdsNewSearchCampaign",
    *,
    status: str,
    today: date,
    declare_eu_political: bool,
) -> str:
    """Adds the budget, campaign, locations, negative keywords, and assets; returns its name.

    Args:
        today: The date in the account time zone. A start on or before it starts the campaign
            when it's turned on, because Google refuses a start time in the past.
        declare_eu_political: If true, sends the campaign's EU political answer. If false,
            leaves it out, as Google allows for a campaign that targets only outside the EU.
    """
    budget = campaign.budget
    if budget.kind == "new":
        budget_name = add_campaign_budget(build, campaign.name, budget.amount_micros)
    else:
        budget_name = (
            f"customers/{budget.budget.customer_id}/campaignBudgets/{budget.budget.budget_id}"
        )
    body: dict[str, Any] = {
        **campaign_body(
            campaign, status=status, today=today, declare_eu_political=declare_eu_political
        ),
        "advertisingChannelType": "SEARCH",
        "campaignBudget": budget_name,
        "networkSettings": {
            "targetGoogleSearch": True,
            "targetSearchNetwork": campaign.search_partners,
            "targetContentNetwork": campaign.display_expansion,
            "targetPartnerSearchNetwork": False,
        },
    }
    name = build.create("campaign", body, label=campaign.name, source=CampaignItem("campaign"))
    if name is None:
        raise ValueError("Google Ads builds must name new campaigns")
    add_campaign_locations(build, campaign, name)
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


def add_campaign_budget(build: CampaignBuild, name: str, amount_micros: int) -> str:
    """Adds a daily budget for the new campaign alone; returns its temporary name."""
    budget = build.create(
        "campaignBudget",
        {
            "name": name,
            "amountMicros": str(amount_micros),
            "deliveryMethod": "STANDARD",
            "explicitlyShared": False,
            "period": "DAILY",
        },
        label=name,
        source=CampaignItem("budget"),
    )
    if budget is None:
        raise ValueError("Google Ads builds must name new budgets")
    return budget


def eu_political_status(contains: bool) -> str:
    """Google's value for the answer to whether the ads are EU political ads."""
    return (
        "CONTAINS_EU_POLITICAL_ADVERTISING"
        if contains
        else "DOES_NOT_CONTAIN_EU_POLITICAL_ADVERTISING"
    )


def campaign_body(
    campaign: "NewCampaign", *, status: str, today: date, declare_eu_political: bool
) -> dict[str, Any]:
    """The settings every new campaign sets: name, status, bidding, locations, and dates."""
    body: dict[str, Any] = {
        "name": campaign.name,
        "status": status,
        "geoTargetTypeSetting": {"positiveGeoTargetType": campaign.location_setting},
        **_bidding(campaign.bidding),
    }
    # An answer of yes is always sent, so a campaign never loses it.
    if declare_eu_political or campaign.contains_eu_political_advertising:
        body["containsEuPoliticalAdvertising"] = eu_political_status(
            campaign.contains_eu_political_advertising
        )
    if campaign.start_date and campaign.start_date > today:
        body["startDateTime"] = f"{campaign.start_date.isoformat()} 00:00:00"
    if campaign.end_date:
        body["endDateTime"] = f"{campaign.end_date.isoformat()} 23:59:59"
    return body


def add_campaign_locations(build: CampaignBuild, campaign: "NewCampaign", name: str) -> None:
    """Adds the campaign's targeted and excluded locations."""
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


def _bidding(bidding: Any) -> dict[str, Any]:
    """The campaign's bidding field; each strategy sets only its own oneof member."""
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
