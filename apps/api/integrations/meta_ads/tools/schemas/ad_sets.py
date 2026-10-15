# apps/api/integrations/meta_ads/tools/schemas/ad_sets.py

"""Input and result contracts for creating one ad set in an existing campaign."""

import re
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...goals import GOALS, MetaAdsConversionEvent, MetaAdsGoal
from ...models import MetaAdsId, MetaAdsStrictModel, MetaAdsText
from ...operations.targeting import MetaAdsTargeting
from ...references import (
    MetaAdsAdSetReference,
    MetaAdsApplicationReference,
    MetaAdsCampaignReference,
    MetaAdsPageReference,
    MetaAdsPixelReference,
)
from .budgets import MetaAdsBidStrategy, MetaAdsBudgetAmount
from .campaigns import MetaAdsNewObjectStatus
from .text import tidy_text

MAX_AD_SET_NAME = 400
MAX_EU_NAME = 512

# Positions Meta still offers in v26: no Facebook video feeds, Instagram Explore, or Messenger story.
type MetaAdsPosition = Literal[
    "facebook:feed",
    "facebook:profile_feed",
    "facebook:right_hand_column",
    "facebook:marketplace",
    "facebook:story",
    "facebook:facebook_reels",
    "facebook:instream_video",
    "facebook:search",
    "instagram:stream",
    "instagram:story",
    "instagram:reels",
    "instagram:profile_feed",
    "instagram:ig_search",
    "audience_network:classic",
    "audience_network:rewarded_video",
    "messenger:messenger_home",
    "threads:threads_stream",
]


def _roas(value: str) -> str:
    if not re.fullmatch(r"[0-9]{1,4}(?:\.[0-9]{1,4})?", value) or Decimal(value) <= 0:
        raise ValueError("Set the minimum return on ad spend as a ratio above zero, such as 2.5.")
    return value


class MetaAdsAdSetBudget(MetaAdsStrictModel):
    kind: Literal["daily", "lifetime"]
    amount: MetaAdsBudgetAmount


class MetaAdsAdSetPlacements(MetaAdsStrictModel):
    mode: Literal["automatic", "manual"] = "automatic"
    positions: list[MetaAdsPosition] = Field(default_factory=list, max_length=17)
    devices: Literal["all", "mobile", "desktop"] = "all"

    @model_validator(mode="after")
    def _positions_for_mode(self) -> Self:
        if (self.mode == "manual") != bool(self.positions):
            raise ValueError("Manual placements need positions; automatic placements take none.")
        if len(set(self.positions)) != len(self.positions):
            raise ValueError("List each position once.")
        return self


class MetaAdsAdSetSettings(MetaAdsStrictModel):
    """Everything about a new ad set but its campaign, which a launch creates first."""

    name: Annotated[str, Field(max_length=MAX_AD_SET_NAME), AfterValidator(tidy_text)]
    goal: MetaAdsGoal
    targeting: MetaAdsTargeting
    page: MetaAdsPageReference | None = None
    pixel: MetaAdsPixelReference | None = None
    conversion_event: MetaAdsConversionEvent | None = None
    custom_conversion_id: MetaAdsId | None = None
    app: MetaAdsApplicationReference | None = None
    app_store: Literal["google_play", "app_store"] | None = None
    placements: MetaAdsAdSetPlacements = Field(default_factory=MetaAdsAdSetPlacements)
    budget: MetaAdsAdSetBudget | None = None
    bid_strategy: MetaAdsBidStrategy | None = None
    bid_amount: MetaAdsBudgetAmount | None = None
    min_roas: Annotated[str, Field(max_length=16), AfterValidator(_roas)] | None = None
    min_daily_spend: MetaAdsBudgetAmount | None = None
    max_daily_spend: MetaAdsBudgetAmount | None = None
    pay_per_click: bool = False
    start_date: str | None = Field(default=None, max_length=10)
    end_date: str | None = Field(default=None, max_length=10)
    eu_payer: Annotated[str, Field(max_length=MAX_EU_NAME), AfterValidator(tidy_text)] | None = None
    eu_beneficiary: (
        Annotated[str, Field(max_length=MAX_EU_NAME), AfterValidator(tidy_text)] | None
    ) = None

    @model_validator(mode="after")
    def _check_settings(self) -> Self:
        if problems := _settings_problems(self):
            raise ValueError(problems[0])
        return self

    @property
    def asset_accounts(self) -> set[str]:
        """Returns the ad accounts of the Page, pixel, app, and audiences the ad set uses."""
        references = [self.page, self.pixel, self.app, *self.targeting.audiences]
        references.extend(self.targeting.excluded_audiences)
        return {item.account_id for item in references if item is not None}


class MetaAdsCreateAdSetRequest(MetaAdsAdSetSettings):
    campaign: MetaAdsCampaignReference
    status: MetaAdsNewObjectStatus = "paused"

    @model_validator(mode="after")
    def _check_account(self) -> Self:
        if self.asset_accounts - {self.account_id}:
            raise ValueError(
                "Use a Page, pixel, app, and audiences from the campaign's ad account."
            )
        return self

    @property
    def account_id(self) -> str:
        return self.campaign.account_id


def _settings_problems(request: MetaAdsAdSetSettings) -> list[str]:
    """Rules that hold whatever the campaign is; campaign rules run against the live campaign."""
    row = GOALS[request.goal]
    problems: list[str] = []
    assets = {"page": request.page, "pixel": request.pixel, "app": request.app}
    if row.asset is not None and assets[row.asset] is None:
        problems.append(f"The goal {request.goal} needs a {row.asset}.")
    if unused := [
        name for name, value in assets.items() if value is not None and name != row.asset
    ]:
        problems.append(f"The goal {request.goal} doesn't use a {unused[0]}; leave it out.")
    if row.asset == "pixel" and (request.conversion_event is None) == (
        request.custom_conversion_id is None
    ):
        problems.append("Set either conversion_event or custom_conversion_id for the pixel.")
    if row.asset != "pixel" and (request.conversion_event or request.custom_conversion_id):
        problems.append("Only website conversion goals take a conversion event.")
    if (row.asset == "app") != (request.app_store is not None):
        problems.append("Set app_store for app installs, and only for them.")
    if request.pay_per_click and not row.clicks_billing:
        problems.append("Only the link_clicks goal can pay per click.")
    if request.budget and request.budget.kind == "lifetime" and not request.end_date:
        problems.append("A lifetime budget needs an end_date.")
    if (
        request.min_daily_spend
        and request.max_daily_spend
        and Decimal(request.max_daily_spend) < Decimal(request.min_daily_spend)
    ):
        problems.append("Set max_daily_spend at or above min_daily_spend.")
    if any(
        location.kind in ("region", "city") and location.country_code is None
        for location in request.targeting.locations
    ):
        problems.append("Keep the country_code meta_ads_search_targeting returned for each place.")
    return problems


type MetaAdsCreatedAdSetOutcome = Literal["created", "failed", "unverified"]
# How the ad set says who pays for and benefits from ads shown in the EU.
type MetaAdsEuTransparency = Literal["not_needed", "sent", "account_defaults"]


class MetaAdsCreatedAdSet(MetaAdsStrictModel):
    name: MetaAdsText
    campaign_id: MetaAdsId
    goal: MetaAdsGoal
    outcome: MetaAdsCreatedAdSetOutcome
    # True when an unclear reply was settled by finding the ad set by name.
    recovered: bool
    # False when the ad set couldn't be read back after it was made.
    verified: bool
    adset_id: MetaAdsId | None
    effective_status: MetaAdsText | None
    # Read back from Meta, ready to pass to meta_ads_create_ads.
    ad_set: MetaAdsAdSetReference | None
    eu_transparency: MetaAdsEuTransparency
    error_code: str | None = Field(default=None, max_length=100)
    message: str | None = Field(default=None, max_length=1000)


class MetaAdsCreateAdSetData(MetaAdsStrictModel):
    account_id: MetaAdsId
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    ad_set: MetaAdsCreatedAdSet


class MetaAdsCreateAdSetEntry(IntegrationFanOutEntry):
    data: MetaAdsCreateAdSetData | None = None


class MetaAdsCreateAdSetOutput(IntegrationFanOutOutput):
    results: list[MetaAdsCreateAdSetEntry]
