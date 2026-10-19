# apps/api/integrations/meta_ads/tools/schemas/ad_edits.py

"""Input and result contracts for renaming and rescheduling existing ads."""

from typing import Literal, Self, get_args

from pydantic import Field, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...models import MetaAdsId, MetaAdsStrictModel, MetaAdsText
from ...references import MetaAdsAdReference
from .ad_set_edits import MetaAdsSettingValue
from .ads import MetaAdsAdName
from .budget_schedules import MetaAdsLocalTime

MAX_AD_EDITS = 50
# Every setting an edit can change, in the order the card and results show them.
type MetaAdsAdSetting = Literal["name", "start_at", "end_at"]
AD_SETTINGS: tuple[MetaAdsAdSetting, ...] = get_args(MetaAdsAdSetting.__value__)

# "none" removes the ad's own time, so it follows its ad set's schedule again.
type MetaAdsAdTime = MetaAdsLocalTime | Literal["none"]


class MetaAdsAdEdit(MetaAdsStrictModel):
    """New values for one ad; an omitted setting stays as it is."""

    ad: MetaAdsAdReference
    name: MetaAdsAdName | None = None
    start_at: MetaAdsAdTime | None = Field(
        default=None,
        description="When the ad starts, as YYYY-MM-DDTHH:MM in the account's time zone, or none.",
    )
    end_at: MetaAdsAdTime | None = Field(
        default=None,
        description="When the ad stops, as YYYY-MM-DDTHH:MM in the account's time zone, or none.",
    )

    @model_validator(mode="after")
    def _one_setting(self) -> Self:
        if not self.settings:
            raise ValueError("Set at least one setting to change for each ad.")
        return self

    @property
    def settings(self) -> tuple[MetaAdsAdSetting, ...]:
        """The settings this edit changes, in display order."""
        return tuple(key for key in AD_SETTINGS if getattr(self, key) is not None)


class MetaAdsUpdateAdsRequest(MetaAdsStrictModel):
    """Every argument of an ad edit, so an edited approval is checked whole."""

    changes: list[MetaAdsAdEdit] = Field(min_length=1, max_length=MAX_AD_EDITS)

    @model_validator(mode="after")
    def _each_once(self) -> Self:
        ids = [(item.ad.account_id, item.ad.ad_id) for item in self.changes]
        if len(set(ids)) != len(ids):
            raise ValueError("List each ad once, with all its changes together.")
        return self


class MetaAdsAdSettingChange(MetaAdsStrictModel):
    setting: MetaAdsAdSetting
    # Null means not set: the ad follows its ad set's schedule.
    before: MetaAdsSettingValue | None
    requested: MetaAdsSettingValue | None
    # Read back after the change; null when not set, or when it couldn't be read.
    after: MetaAdsSettingValue | None


class MetaAdsAdEditOutcome(MetaAdsStrictModel):
    ad_id: MetaAdsId
    name: MetaAdsText | None
    changes: list[MetaAdsAdSettingChange] = Field(max_length=len(AD_SETTINGS))
    outcome: Literal["updated", "already_set", "failed", "unverified"]
    error_code: str | None = Field(default=None, max_length=100)
    message: str | None = Field(default=None, max_length=1000)


class MetaAdsUpdateAdsData(MetaAdsStrictModel):
    account_id: MetaAdsId
    # The IANA zone the times are in, such as Europe/London.
    time_zone: str = Field(max_length=64)
    ads: list[MetaAdsAdEditOutcome] = Field(max_length=MAX_AD_EDITS)


class MetaAdsUpdateAdsEntry(IntegrationFanOutEntry):
    data: MetaAdsUpdateAdsData | None = None


class MetaAdsUpdateAdsOutput(IntegrationFanOutOutput):
    results: list[MetaAdsUpdateAdsEntry]
