# apps/api/integrations/meta_ads/tools/schemas/ad_set_edits.py

"""Input and result contracts for changing the settings of existing ad sets."""

from typing import Literal, Self, get_args

from pydantic import Field, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...models import MetaAdsId, MetaAdsStrictModel, MetaAdsText
from ...references import MetaAdsAdSetReference
from .ad_sets import MetaAdsAdSetName, MetaAdsEuName, MetaAdsMinRoas
from .budgets import MetaAdsBidStrategy, MetaAdsBudgetAmount

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

    @model_validator(mode="after")
    def _one_setting(self) -> Self:
        if not self.settings:
            raise ValueError("Set at least one setting to change for each ad set.")
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


class MetaAdsSettingChange(MetaAdsStrictModel):
    setting: MetaAdsAdSetSetting
    # Null means not set: no end date, no spend limit, or no bid.
    before: MetaAdsText | None
    requested: MetaAdsText | None
    # Read back after the change; null when not set, or when it couldn't be read.
    after: MetaAdsText | None


class MetaAdsAdSetEditOutcome(MetaAdsStrictModel):
    adset_id: MetaAdsId
    name: MetaAdsText | None
    changes: list[MetaAdsSettingChange] = Field(max_length=len(AD_SET_SETTINGS))
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
