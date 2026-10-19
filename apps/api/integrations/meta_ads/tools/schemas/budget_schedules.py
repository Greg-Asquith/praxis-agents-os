# apps/api/integrations/meta_ads/tools/schemas/budget_schedules.py

"""Input and result contracts for scheduling Meta budget increases in high-demand periods."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...models import MetaAdsId, MetaAdsMoney, MetaAdsStrictModel, MetaAdsText
from ...references import MetaAdsAdSetReference, MetaAdsCampaignReference
from .budgets import MetaAdsBudgetAmount

MAX_NEW_PERIODS = 10
# Meta's limit on high-demand periods per campaign or ad set.
MAX_PERIODS = 50

type MetaAdsLocalTime = Annotated[
    str,
    Field(
        pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}$",
        description="Local time in the ad account's time zone, as YYYY-MM-DDTHH:MM.",
    ),
]


class MetaAdsBudgetPeriod(MetaAdsStrictModel):
    """One high-demand period and how much the daily budget rises during it."""

    start: MetaAdsLocalTime
    end: MetaAdsLocalTime
    increase_amount: MetaAdsBudgetAmount | None = Field(
        default=None,
        description="Amount added to the daily budget, in the ad account currency.",
    )
    increase_percent: int | None = Field(
        default=None,
        ge=1,
        le=700,
        description="Percentage added to the daily budget, for example 50 for half as much again.",
    )

    @model_validator(mode="after")
    def _check_increase(self) -> Self:
        if (self.increase_amount is None) == (self.increase_percent is None):
            raise ValueError("Set exactly one of increase_amount or increase_percent.")
        return self


class MetaAdsScheduleBudgetIncreasesRequest(MetaAdsStrictModel):
    """Every argument of a budget schedule change, so an edited approval is checked whole."""

    campaign: MetaAdsCampaignReference | None = Field(
        default=None, description="Campaign that holds a daily campaign budget."
    )
    ad_set: MetaAdsAdSetReference | None = Field(
        default=None, description="Ad set that holds its own daily budget."
    )
    periods: list[MetaAdsBudgetPeriod] = Field(min_length=1, max_length=MAX_NEW_PERIODS)

    @model_validator(mode="after")
    def _check_target(self) -> Self:
        if (self.campaign is None) == (self.ad_set is None):
            raise ValueError("Set exactly one of campaign or ad_set.")
        return self

    @property
    def reference(self) -> MetaAdsCampaignReference | MetaAdsAdSetReference:
        reference = self.campaign or self.ad_set
        if reference is None:
            raise ValueError("Meta Ads budget schedule has no reference")
        return reference


class MetaAdsScheduledPeriod(MetaAdsStrictModel):
    # Null for a period Meta didn't confirm, or one not sent.
    id: MetaAdsId | None
    # Local times in the ad account's time zone.
    start: str = Field(max_length=32)
    end: str = Field(max_length=32)
    increase_amount: MetaAdsMoney
    increase_percent: int | None
    outcome: Literal["added", "failed", "unverified"]
    error_code: str | None = Field(default=None, max_length=100)
    message: str | None = Field(default=None, max_length=1000)


class MetaAdsBudgetScheduleData(MetaAdsStrictModel):
    account_id: MetaAdsId
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    time_zone: str = Field(max_length=64)
    object_type: Literal["campaign", "adset"]
    object_id: MetaAdsId
    object_name: MetaAdsText | None
    daily_budget: MetaAdsMoney
    periods: list[MetaAdsScheduledPeriod] = Field(max_length=MAX_NEW_PERIODS)


class MetaAdsBudgetScheduleEntry(IntegrationFanOutEntry):
    data: MetaAdsBudgetScheduleData | None = None


class MetaAdsBudgetScheduleOutput(IntegrationFanOutOutput):
    results: list[MetaAdsBudgetScheduleEntry]
