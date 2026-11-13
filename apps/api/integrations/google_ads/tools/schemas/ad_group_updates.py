# apps/api/integrations/google_ads/tools/schemas/ad_group_updates.py

"""Arguments and result contract for changing the settings of live Google Ads ad groups."""

from typing import Annotated, Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...operations.ad_group_settings import AdGroupSetting
from ...operations.campaign_bidding import money
from ...references import GoogleAdsAdGroupReference
from ..utils.money import money_to_micros
from .base import GoogleAdsStrictModel, money_validator
from .campaigns import GoogleAdsTargetCpa
from .url_options import GoogleAdsUrlOptions, GoogleAdsUrlParameter

MAX_AD_GROUP_UPDATES = 50


type _CpcBid = Annotated[str, Field(max_length=32), money_validator("CPC bid")]


class GoogleAdsAdGroupUpdate(GoogleAdsStrictModel):
    """One ad group and only the settings that change."""

    ad_group: GoogleAdsAdGroupReference
    name: str | None = Field(default=None, min_length=1, max_length=255)
    # The default click bid, which only manual bidding uses.
    cpc_bid: _CpcBid | None = None
    # "none" removes the override, so the ad group follows the campaign's target.
    target_cpa: Literal["none"] | GoogleAdsTargetCpa | None = None
    # A ratio, so 3.5 means 350%.
    target_roas: Literal["none"] | Annotated[float, Field(ge=0.01, le=1000)] | None = None
    url_options: GoogleAdsUrlOptions | None = None
    ad_rotation: Literal["OPTIMIZE", "ROTATE_FOREVER"] | None = None

    @field_validator("name", mode="before")
    @classmethod
    def _normalise_name(cls, value: object) -> object:
        # Google refuses line breaks in names.
        return " ".join(value.split()) if isinstance(value, str) else value

    @model_validator(mode="after")
    def _something_changes(self) -> Self:
        if not self.requested:
            raise ValueError(
                f"Name at least one setting to change for ad group {self.ad_group.label}."
            )
        return self

    @property
    def resource_name(self) -> str:
        return f"customers/{self.ad_group.customer_id}/adGroups/{self.ad_group.ad_group_id}"

    @property
    def requested(self) -> dict[AdGroupSetting, Any]:
        """The settings that change, in card terms: money as a canonical decimal, removal as null."""
        values: dict[AdGroupSetting, Any] = {}
        if self.name is not None:
            values["name"] = self.name
        if self.cpc_bid is not None:
            values["cpc_bid"] = money(money_to_micros(self.cpc_bid))
        if self.target_cpa is not None:
            values["target_cpa"] = (
                None if self.target_cpa == "none" else money(money_to_micros(self.target_cpa))
            )
        if self.target_roas is not None:
            values["target_roas"] = None if self.target_roas == "none" else self.target_roas
        if self.url_options is not None:
            values.update(self.url_options.requested)
        if self.ad_rotation is not None:
            values["ad_rotation"] = self.ad_rotation
        return values


class GoogleAdsUpdateAdGroupsRequest(GoogleAdsStrictModel):
    """Every argument of an ad group update, so an edited approval is checked whole."""

    changes: list[GoogleAdsAdGroupUpdate] = Field(min_length=1, max_length=MAX_AD_GROUP_UPDATES)

    @model_validator(mode="after")
    def _each_once(self) -> Self:
        names = [change.resource_name for change in self.changes]
        if len(set(names)) != len(names):
            raise ValueError("List each ad group once, with all of its changes.")
        return self


type GoogleAdsAdGroupSettingValue = str | float | list[GoogleAdsUrlParameter] | None


class GoogleAdsAdGroupSettingOutcome(GoogleAdsStrictModel):
    setting: AdGroupSetting
    # As the approval card showed it.
    before: GoogleAdsAdGroupSettingValue
    requested: GoogleAdsAdGroupSettingValue
    # Read back after the change; meaningful only when the ad group's `read_back` is true.
    after: GoogleAdsAdGroupSettingValue
    outcome: Literal["updated", "already_set", "failed", "unverified"]


class GoogleAdsAdGroupUpdateOutcome(GoogleAdsStrictModel):
    resource_name: str
    ad_group_id: str
    name: str
    campaign_name: str
    read_back: bool
    settings: list[GoogleAdsAdGroupSettingOutcome] = Field(max_length=8)
    error_code: str | None = None
    message: str | None = None


class GoogleAdsUpdateAdGroupsData(GoogleAdsStrictModel):
    account_id: str
    currency: str
    ad_groups: list[GoogleAdsAdGroupUpdateOutcome] = Field(max_length=MAX_AD_GROUP_UPDATES)


class GoogleAdsUpdateAdGroupsEntry(IntegrationFanOutEntry):
    data: GoogleAdsUpdateAdGroupsData | None = None


class GoogleAdsUpdateAdGroupsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsUpdateAdGroupsEntry]
