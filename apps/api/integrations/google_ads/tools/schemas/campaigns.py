# apps/api/integrations/google_ads/tools/schemas/campaigns.py

"""Arguments and result contract for creating a complete Google Ads Search campaign."""

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

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
from .base import GoogleAdsStrictModel, money_validator
from .campaign_budgets import GoogleAdsMoneyAmount
from .negative_keywords import NegativeKeywordEntry

MAX_CAMPAIGN_LOCATIONS = 1_000
MAX_CAMPAIGN_NEGATIVES = 1_000

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


class GoogleAdsNewSearchCampaign(GoogleAdsStrictModel):
    """The campaign's own settings, without its ad groups."""

    name: str = Field(min_length=1, max_length=255)
    budget: GoogleAdsCampaignBudgetChoice
    bidding: GoogleAdsSearchBidding
    search_partners: bool = False
    display_expansion: bool = False
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
    negative_keywords: list[NegativeKeywordEntry] = Field(
        default_factory=list, max_length=MAX_CAMPAIGN_NEGATIVES
    )
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
    def _consistent(self) -> Self:
        keys = [item.key for item in (*self.locations, *self.excluded_locations)]
        if len(set(keys)) != len(keys):
            raise ValueError("List each location once, as targeted or excluded.")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("The end date must be on or after the start date.")
        distinct_keywords(self.negative_keywords, scope="campaign")
        return self

    @property
    def object_count(self) -> int:
        budget = 1 if isinstance(self.budget, GoogleAdsNewDailyBudget) else 0
        return (
            budget
            + 1
            + len(self.locations)
            + len(self.excluded_locations)
            + len(self.negative_keywords)
        )


class GoogleAdsCreateCampaignRequest(GoogleAdsStrictModel):
    """Every argument of a campaign creation, so an edited approval is checked whole."""

    campaign: GoogleAdsNewSearchCampaign
    ad_groups: list[GoogleAdsNewAdGroup] = Field(min_length=1, max_length=MAX_NEW_AD_GROUPS)
    status: Literal["PAUSED", "ENABLED"] = "PAUSED"

    @model_validator(mode="after")
    def _whole_request(self) -> Self:
        names = [ad_group.name.casefold() for ad_group in self.ad_groups]
        if len(set(names)) != len(names):
            raise ValueError("Give each new ad group a different name.")
        total = self.campaign.object_count + sum(group.object_count for group in self.ad_groups)
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
    requested_status: Literal["PAUSED", "ENABLED"]
    outcome: Literal["created", "failed", "unverified"]
    # Set when created, for the agent to pass to other tools.
    campaign: GoogleAdsCampaignReference | None = None
    kinds: list[GoogleAdsCampaignKindCount] = Field(max_length=8)
    ad_groups: list[GoogleAdsCreatedAdGroup] = Field(max_length=MAX_NEW_AD_GROUPS)
    problems: list[GoogleAdsCampaignProblemRow] = Field(max_length=MAX_RESULT_PROBLEMS)


class GoogleAdsCreateCampaignEntry(IntegrationFanOutEntry):
    data: GoogleAdsCreateCampaignData | None = None


class GoogleAdsCreateCampaignOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsCreateCampaignEntry]
