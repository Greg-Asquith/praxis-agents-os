# apps/api/integrations/meta_ads/tools/schemas/ad_set_edits.py

"""Input and result contracts for changing the settings of existing ad sets."""

from typing import Annotated, Literal, Self, get_args

from pydantic import Field, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...goals import MetaAdsConversionEvent, MetaAdsGoal
from ...models import MetaAdsId, MetaAdsStrictModel, MetaAdsText
from ...references import (
    MetaAdsAdSetReference,
    MetaAdsApplicationReference,
    MetaAdsPageReference,
    MetaAdsPixelReference,
)
from .ad_sets import MetaAdsAdSetName, MetaAdsEuName, MetaAdsMinRoas
from .budgets import MetaAdsBidStrategy, MetaAdsBudgetAmount
from .delivery import MetaAdsAdSchedule, MetaAdsAttribution, MetaAdsFrequencyCap

MAX_AD_SET_EDITS = 50
# Every setting an edit can change, in the order the card and results show them.
type MetaAdsAdSetSetting = Literal[
    "name",
    "start_date",
    "end_date",
    "bid_strategy",
    "bid_amount",
    "min_roas",
    "min_daily_spend",
    "max_daily_spend",
    "min_lifetime_spend",
    "max_lifetime_spend",
    "eu_payer",
    "eu_beneficiary",
    "goal",
    "pixel",
    "conversion_event",
    "custom_conversion_id",
    "page",
    "app",
    "app_store",
    "attribution",
    "frequency_cap",
    "ad_schedule",
]
AD_SET_SETTINGS: tuple[MetaAdsAdSetSetting, ...] = get_args(MetaAdsAdSetSetting.__value__)

type MetaAdsSpendControl = MetaAdsBudgetAmount | Literal["remove"]


class MetaAdsAdSetEdit(MetaAdsStrictModel):
    """New values for one ad set; an omitted setting stays as it is."""

    ad_set: MetaAdsAdSetReference
    name: MetaAdsAdSetName | None = None
    start_date: str | None = Field(
        default=None, max_length=10, description="YYYY-MM-DD in the account's time zone."
    )
    end_date: str | None = Field(
        default=None,
        max_length=10,
        description="YYYY-MM-DD in the account's time zone, or none to run continuously.",
    )
    bid_strategy: MetaAdsBidStrategy | None = None
    bid_amount: MetaAdsBudgetAmount | None = None
    min_roas: MetaAdsMinRoas | None = None
    min_daily_spend: MetaAdsSpendControl | None = None
    max_daily_spend: MetaAdsSpendControl | None = None
    min_lifetime_spend: MetaAdsSpendControl | None = None
    max_lifetime_spend: MetaAdsSpendControl | None = None
    eu_payer: MetaAdsEuName | None = None
    eu_beneficiary: MetaAdsEuName | None = None
    goal: MetaAdsGoal | None = Field(
        default=None, description="A goal for the campaign's objective and the same destination."
    )
    pixel: MetaAdsPixelReference | None = None
    conversion_event: MetaAdsConversionEvent | None = None
    custom_conversion_id: MetaAdsId | None = Field(
        default=None, description="From meta_ads_list_conversions, instead of conversion_event."
    )
    page: MetaAdsPageReference | None = None
    app: MetaAdsApplicationReference | None = None
    app_store: Literal["google_play", "app_store"] | None = None
    attribution: MetaAdsAttribution | None = None
    frequency_cap: MetaAdsFrequencyCap | Literal["remove"] | None = None
    ad_schedule: MetaAdsAdSchedule | Literal["remove"] | None = None

    @model_validator(mode="after")
    def _one_setting(self) -> Self:
        if not self.settings:
            raise ValueError("Set at least one setting to change for each ad set.")
        if self.conversion_event is not None and self.custom_conversion_id is not None:
            raise ValueError("Set conversion_event or custom_conversion_id, not both.")
        if (self.app is None) != (self.app_store is None):
            raise ValueError("Set app and app_store together.")
        accounts = {item.account_id for item in (self.pixel, self.page, self.app) if item}
        if accounts - {self.ad_set.account_id}:
            raise ValueError("Use a Page, pixel, and app from the ad set's ad account.")
        return self

    @property
    def settings(self) -> tuple[MetaAdsAdSetSetting, ...]:
        """The settings this edit changes, in display order."""
        return tuple(key for key in AD_SET_SETTINGS if getattr(self, key) is not None)


class MetaAdsUpdateAdSetsRequest(MetaAdsStrictModel):
    """Every argument of an ad set edit, so an edited approval is checked whole."""

    changes: list[MetaAdsAdSetEdit] = Field(min_length=1, max_length=MAX_AD_SET_EDITS)

    @model_validator(mode="after")
    def _each_once(self) -> Self:
        ids = [(item.ad_set.account_id, item.ad_set.adset_id) for item in self.changes]
        if len(set(ids)) != len(ids):
            raise ValueError("List each ad set once, with all its changes together.")
        return self


# Room for a week of ad scheduling, which the card reads as compact JSON.
type MetaAdsSettingValue = Annotated[str, Field(max_length=1000)]


class MetaAdsSettingChange(MetaAdsStrictModel):
    setting: MetaAdsAdSetSetting
    # Null means not set: no end date, no spend limit, or no bid.
    before: MetaAdsSettingValue | None
    requested: MetaAdsSettingValue | None
    # Read back after the change; null when not set, or when it couldn't be read.
    after: MetaAdsSettingValue | None


class MetaAdsAssetLabel(MetaAdsStrictModel):
    id: MetaAdsId
    name: MetaAdsText


class MetaAdsAdSetEditOutcome(MetaAdsStrictModel):
    adset_id: MetaAdsId
    name: MetaAdsText | None
    changes: list[MetaAdsSettingChange] = Field(max_length=len(AD_SET_SETTINGS))
    # Names of the Pages, pixels, apps, and custom conversions in the changes.
    labels: list[MetaAdsAssetLabel] = Field(default_factory=list, max_length=12)
    outcome: Literal["updated", "already_set", "failed", "unverified"]
    error_code: str | None = Field(default=None, max_length=100)
    message: str | None = Field(default=None, max_length=1000)


class MetaAdsUpdateAdSetsData(MetaAdsStrictModel):
    account_id: MetaAdsId
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    ad_sets: list[MetaAdsAdSetEditOutcome] = Field(max_length=MAX_AD_SET_EDITS)


class MetaAdsUpdateAdSetsEntry(IntegrationFanOutEntry):
    data: MetaAdsUpdateAdSetsData | None = None


class MetaAdsUpdateAdSetsOutput(IntegrationFanOutOutput):
    results: list[MetaAdsUpdateAdSetsEntry]
