# apps/api/integrations/google_ads/tools/schemas/campaigns.py

"""Arguments and result contract for creating a complete Search or Performance Max campaign."""

from datetime import date
from typing import Annotated, Any, Literal, Self

from pydantic import Discriminator, Field, Tag, field_validator, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...references import GoogleAdsCampaignBudgetReference, GoogleAdsCampaignReference
from ..utils.money import money_to_micros
from .ad_groups import (
    MAX_NEW_AD_GROUPS,
    MAX_OBJECTS,
    MAX_RESULT_PROBLEMS,
    GoogleAdsCreatedAdGroup,
    GoogleAdsNewAdGroup,
    distinct_keywords,
)
from .assets import MAX_ASSETS_PER_TARGET, GoogleAdsNewAsset, distinct_new_assets
from .base import GoogleAdsStrictModel, money_validator
from .campaign_budgets import GoogleAdsMoneyAmount
from .negative_keywords import NegativeKeywordEntry
from .performance_max import (
    MAX_LOGOS,
    MAX_NEW_ASSET_GROUPS,
    GoogleAdsCampaignLogo,
    GoogleAdsCreatedAssetGroup,
    GoogleAdsNewAssetGroup,
    GoogleAdsVideoPages,
)

MAX_CAMPAIGN_LOCATIONS = 1_000
MAX_CAMPAIGN_NEGATIVES = 1_000
MAX_CAMPAIGN_LANGUAGES = 50

type _Key = Annotated[str, Field(pattern=r"^[0-9]{1,20}$")]


def _micros(value: str | None) -> int | None:
    return money_to_micros(value) if value else None


def _blank_is_none(value: object) -> object:
    return None if isinstance(value, str) and not value.strip() else value


type GoogleAdsMaxCpc = Annotated[str, Field(max_length=32), money_validator("maximum click bid")]
type GoogleAdsTargetCpa = Annotated[str, Field(max_length=32), money_validator("target CPA")]


class GoogleAdsNewDailyBudget(GoogleAdsStrictModel):
    """A new budget for this campaign alone."""

    kind: Literal["new"] = "new"
    daily_amount: GoogleAdsMoneyAmount

    @property
    def amount_micros(self) -> int:
        return money_to_micros(self.daily_amount)


class GoogleAdsSharedBudget(GoogleAdsStrictModel):
    """An existing shared budget the campaign spends from with other campaigns."""

    kind: Literal["shared"]
    budget: GoogleAdsCampaignBudgetReference


type GoogleAdsCampaignBudgetChoice = Annotated[
    GoogleAdsNewDailyBudget | GoogleAdsSharedBudget, Field(discriminator="kind")
]


class GoogleAdsManualCpc(GoogleAdsStrictModel):
    strategy: Literal["MANUAL_CPC"]


class GoogleAdsMaximizeClicks(GoogleAdsStrictModel):
    strategy: Literal["MAXIMIZE_CLICKS"]
    max_cpc: GoogleAdsMaxCpc | None = None

    @field_validator("max_cpc", mode="before")
    @classmethod
    def _blank(cls, value: object) -> object:
        return _blank_is_none(value)

    @property
    def max_cpc_micros(self) -> int | None:
        return _micros(self.max_cpc)


class GoogleAdsMaximizeConversions(GoogleAdsStrictModel):
    strategy: Literal["MAXIMIZE_CONVERSIONS"]
    target_cpa: GoogleAdsTargetCpa | None = None

    @field_validator("target_cpa", mode="before")
    @classmethod
    def _blank(cls, value: object) -> object:
        return _blank_is_none(value)

    @property
    def target_cpa_micros(self) -> int | None:
        return _micros(self.target_cpa)


class GoogleAdsMaximizeConversionValue(GoogleAdsStrictModel):
    strategy: Literal["MAXIMIZE_CONVERSION_VALUE"]
    # A ratio, so 3.5 means 350%.
    target_roas: float | None = Field(default=None, ge=0.01, le=1000)

    @field_validator("target_roas", mode="before")
    @classmethod
    def _blank(cls, value: object) -> object:
        return _blank_is_none(value)


class GoogleAdsTargetImpressionShare(GoogleAdsStrictModel):
    strategy: Literal["TARGET_IMPRESSION_SHARE"]
    location: Literal["ANYWHERE_ON_PAGE", "TOP_OF_PAGE", "ABSOLUTE_TOP_OF_PAGE"]
    share_percent: int = Field(ge=1, le=100)
    # Google requires a ceiling for this strategy.
    max_cpc: GoogleAdsMaxCpc

    @property
    def max_cpc_micros(self) -> int | None:
        return _micros(self.max_cpc)


type GoogleAdsSearchBidding = Annotated[
    GoogleAdsManualCpc
    | GoogleAdsMaximizeClicks
    | GoogleAdsMaximizeConversions
    | GoogleAdsMaximizeConversionValue
    | GoogleAdsTargetImpressionShare,
    Field(discriminator="strategy"),
]


class GoogleAdsCampaignLocation(GoogleAdsStrictModel):
    key: _Key
    # For display until Google's own name is read back.
    name: str | None = Field(default=None, max_length=500)


class NewCampaign(GoogleAdsStrictModel):
    """The settings every new campaign takes, whatever its type."""

    name: str = Field(min_length=1, max_length=255)
    locations: list[GoogleAdsCampaignLocation] = Field(
        default_factory=list, max_length=MAX_CAMPAIGN_LOCATIONS
    )
    excluded_locations: list[GoogleAdsCampaignLocation] = Field(
        default_factory=list, max_length=MAX_CAMPAIGN_LOCATIONS
    )
    location_setting: Literal["PRESENCE", "PRESENCE_OR_INTEREST"] = "PRESENCE"
    # Dates in the account time zone; no start date starts the campaign when it's turned on.
    start_date: date | None = None
    end_date: date | None = None
    contains_eu_political_advertising: bool = False

    @field_validator("name", mode="before")
    @classmethod
    def _normalise_name(cls, value: object) -> object:
        # Google refuses line breaks in names.
        return " ".join(value.split()) if isinstance(value, str) else value

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def _blank_date(cls, value: object) -> object:
        return _blank_is_none(value)

    @model_validator(mode="after")
    def _consistent_basics(self) -> Self:
        keys = [item.key for item in (*self.locations, *self.excluded_locations)]
        if len(set(keys)) != len(keys):
            raise ValueError("List each location once, as targeted or excluded.")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("The end date must be on or after the start date.")
        return self

    @property
    def location_count(self) -> int:
        return len(self.locations) + len(self.excluded_locations)


class GoogleAdsNewSearchCampaign(NewCampaign):
    """A Search campaign's own settings, without its ad groups."""

    type: Literal["search"] = "search"
    budget: GoogleAdsCampaignBudgetChoice
    bidding: GoogleAdsSearchBidding
    search_partners: bool = False
    display_expansion: bool = False
    negative_keywords: list[NegativeKeywordEntry] = Field(
        default_factory=list, max_length=MAX_CAMPAIGN_NEGATIVES
    )
    assets: list[GoogleAdsNewAsset] = Field(
        default_factory=list,
        max_length=MAX_ASSETS_PER_TARGET,
        description="New sitelinks and callouts for every ad group in the campaign.",
    )

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        distinct_keywords(self.negative_keywords, scope="campaign")
        distinct_new_assets(self.assets)
        return self

    @property
    def object_count(self) -> int:
        budget = 1 if isinstance(self.budget, GoogleAdsNewDailyBudget) else 0
        return budget + 1 + self.location_count + len(self.negative_keywords) + 2 * len(self.assets)


type GoogleAdsPerformanceMaxBidding = Annotated[
    GoogleAdsMaximizeConversions | GoogleAdsMaximizeConversionValue,
    Field(discriminator="strategy"),
]


class GoogleAdsCampaignLanguage(GoogleAdsStrictModel):
    key: _Key
    name: str | None = Field(default=None, max_length=500)


class GoogleAdsCampaignGoal(GoogleAdsStrictModel):
    """An account conversion goal, by Google's category and origin, such as PURCHASE, WEBSITE."""

    category: str = Field(pattern=r"^[A-Z_]{1,64}$")
    origin: str = Field(pattern=r"^[A-Z_]{1,64}$")


class GoogleAdsMerchantFeed(GoogleAdsStrictModel):
    merchant_id: str = Field(
        pattern=r"^[0-9]{1,20}$",
        description="A Merchant Center account linked to this Google Ads account.",
    )
    feed_label: str | None = Field(
        default=None,
        max_length=20,
        description="Only products with this feed label. Leave out for every feed.",
    )

    @field_validator("feed_label", mode="before")
    @classmethod
    def _blank(cls, value: object) -> object:
        value = value.strip() if isinstance(value, str) else value
        return value or None


class GoogleAdsNewPerformanceMaxCampaign(NewCampaign):
    """A Performance Max campaign's own settings and brand, without its asset groups."""

    type: Literal["performance_max"]
    # Google doesn't let Performance Max spend from a shared budget.
    budget: GoogleAdsNewDailyBudget
    bidding: GoogleAdsPerformanceMaxBidding
    languages: list[GoogleAdsCampaignLanguage] = Field(
        default_factory=list,
        max_length=MAX_CAMPAIGN_LANGUAGES,
        description="Language keys from google_ads_search_targeting; none means every language.",
    )
    business_name: str | None = Field(default=None, max_length=25)
    logos: list[GoogleAdsCampaignLogo] = Field(default_factory=list, max_length=MAX_LOGOS)
    final_url_expansion: bool = True
    # Google looks for videos on these pages; none leaves that off, as Google does.
    video_pages: GoogleAdsVideoPages = Field(default_factory=list)
    # None bids for the account's goals; a list bids for those goals in this campaign only.
    conversion_goals: list[GoogleAdsCampaignGoal] | None = Field(default=None, max_length=100)
    merchant: GoogleAdsMerchantFeed | None = None

    @field_validator("business_name", mode="before")
    @classmethod
    def _tidy_business_name(cls, value: object) -> object:
        return _blank_is_none(" ".join(value.split()) if isinstance(value, str) else value)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if len({item.key for item in self.languages}) != len(self.languages):
            raise ValueError("List each language once.")
        if len({item.asset.asset_id for item in self.logos}) != len(self.logos):
            raise ValueError("List each logo once.")
        goals = [(goal.category, goal.origin) for goal in self.conversion_goals or ()]
        if len(set(goals)) != len(goals):
            raise ValueError("List each conversion goal once.")
        return self

    @property
    def object_count(self) -> int:
        brand = 2 if self.business_name else 0
        return 2 + self.location_count + len(self.languages) + brand + len(self.logos)


def _campaign_type(value: Any) -> str:
    kind = value.get("type") if isinstance(value, dict) else getattr(value, "type", None)
    return kind or "search"


type GoogleAdsNewCampaign = Annotated[
    Annotated[GoogleAdsNewSearchCampaign, Tag("search")]
    | Annotated[GoogleAdsNewPerformanceMaxCampaign, Tag("performance_max")],
    Discriminator(_campaign_type),
]


def performance_max_brand_problems(
    campaign: GoogleAdsNewPerformanceMaxCampaign, asset_groups: list[GoogleAdsNewAssetGroup]
) -> list[str]:
    """What the campaign's brand needs, with brand guidelines on.

    A retail campaign whose asset groups link none of their own assets needs no brand, because
    Google makes the assets from the feed.
    """
    retail_only = campaign.merchant is not None and not any(g.has_assets for g in asset_groups)
    if retail_only and not campaign.business_name and not campaign.logos:
        return []
    problems = []
    if not campaign.business_name:
        problems.append("Add the business name, as it should appear in the ads.")
    if not any(logo.field_type == "LOGO" for logo in campaign.logos):
        problems.append("Add at least one square logo.")
    return problems


class GoogleAdsCreateCampaignRequest(GoogleAdsStrictModel):
    """Every argument of a campaign creation, so an edited approval is checked whole."""

    campaign: GoogleAdsNewCampaign
    ad_groups: list[GoogleAdsNewAdGroup] = Field(default_factory=list, max_length=MAX_NEW_AD_GROUPS)
    asset_groups: list[GoogleAdsNewAssetGroup] = Field(
        default_factory=list, max_length=MAX_NEW_ASSET_GROUPS
    )
    status: Literal["PAUSED", "ENABLED"] = "PAUSED"

    @model_validator(mode="after")
    def _whole_request(self) -> Self:
        groups: list[Any]
        if self.campaign.type == "search":
            if not self.ad_groups or self.asset_groups:
                raise ValueError("A Search campaign takes ad_groups, and no asset_groups.")
            groups = self.ad_groups
        else:
            if not self.asset_groups or self.ad_groups:
                raise ValueError(
                    "A Performance Max campaign takes 1 to 5 asset_groups, and no ad_groups."
                )
            groups = self.asset_groups
        names = [group.name.casefold() for group in groups]
        if len(set(names)) != len(names):
            raise ValueError("Give each new group a different name.")
        total = self.campaign.object_count + sum(group.object_count for group in groups)
        if total > MAX_OBJECTS:
            raise ValueError(f"One request can create at most {MAX_OBJECTS:,} objects.")
        return self


type GoogleAdsCampaignBuildKind = Literal[
    "budget",
    "campaign",
    "location",
    "excluded_location",
    "ad_group",
    "keyword",
    "negative_keyword",
    "ad",
    "asset",
    "asset_link",
    "language",
    "conversion_goal",
    "text_asset",
    "brand_link",
    "asset_group",
    "listing_filter",
    "asset_group_link",
    "search_theme",
    "audience",
    "audience_signal",
]


class GoogleAdsCampaignKindCount(GoogleAdsStrictModel):
    kind: GoogleAdsCampaignBuildKind
    created: int = Field(ge=0)
    failed: int = Field(ge=0)
    unverified: int = Field(ge=0)


class GoogleAdsCampaignProblemRow(GoogleAdsStrictModel):
    item: str
    kind: GoogleAdsCampaignBuildKind
    message: str
    error_code: str | None = None


class GoogleAdsCreateCampaignData(GoogleAdsStrictModel):
    account_id: str
    campaign_name: str
    campaign_type: Literal["search", "performance_max"] = "search"
    requested_status: Literal["PAUSED", "ENABLED"]
    outcome: Literal["created", "failed", "unverified"]
    # Set when created, for the agent to pass to other tools.
    campaign: GoogleAdsCampaignReference | None = None
    kinds: list[GoogleAdsCampaignKindCount] = Field(max_length=20)
    ad_groups: list[GoogleAdsCreatedAdGroup] = Field(
        default_factory=list, max_length=MAX_NEW_AD_GROUPS
    )
    asset_groups: list[GoogleAdsCreatedAssetGroup] = Field(
        default_factory=list, max_length=MAX_NEW_ASSET_GROUPS
    )
    problems: list[GoogleAdsCampaignProblemRow] = Field(max_length=MAX_RESULT_PROBLEMS)


class GoogleAdsCreateCampaignEntry(IntegrationFanOutEntry):
    data: GoogleAdsCreateCampaignData | None = None


class GoogleAdsCreateCampaignOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsCreateCampaignEntry]
