# apps/api/integrations/google_ads/tools/schemas/campaign_updates.py

"""Arguments and result contract for changing the settings of live Google Ads campaigns."""

from datetime import date
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...operations.campaign_settings import CampaignSetting
from ...operations.url_custom_parameters import validate_url_custom_parameter_items
from ...references import GoogleAdsCampaignReference
from .base import GoogleAdsStrictModel

MAX_CAMPAIGN_UPDATES = 50
# Google's limit for campaign URL fields.
_MAX_URL = 2_048


class GoogleAdsUrlParameter(GoogleAdsStrictModel):
    key: str = Field(min_length=1, max_length=16)
    value: str = Field(max_length=200)


class GoogleAdsUrlOptions(GoogleAdsStrictModel):
    """Each field set replaces the campaign's value; an empty value or list clears it."""

    final_url_suffix: str | None = Field(default=None, max_length=_MAX_URL)
    tracking_template: str | None = Field(default=None, max_length=_MAX_URL)
    custom_parameters: list[GoogleAdsUrlParameter] | None = Field(default=None, max_length=8)

    @field_validator("final_url_suffix", "tracking_template")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("custom_parameters")
    @classmethod
    def _valid_parameters(
        cls, value: list[GoogleAdsUrlParameter] | None
    ) -> list[GoogleAdsUrlParameter] | None:
        if value is not None:
            validate_url_custom_parameter_items([(item.key, item.value) for item in value])
        return value


class GoogleAdsCampaignNetworks(GoogleAdsStrictModel):
    search_partners: bool | None = None
    display_expansion: bool | None = None


class GoogleAdsCampaignUpdate(GoogleAdsStrictModel):
    """One campaign and only the settings that change."""

    campaign: GoogleAdsCampaignReference
    name: str | None = Field(default=None, min_length=1, max_length=255)
    # Dates in the account time zone.
    start_date: date | None = None
    # "none" runs the campaign with no end date.
    end_date: date | Literal["none"] | None = None
    url_options: GoogleAdsUrlOptions | None = None
    networks: GoogleAdsCampaignNetworks | None = None

    @field_validator("name", mode="before")
    @classmethod
    def _normalise_name(cls, value: object) -> object:
        # Google refuses line breaks in names.
        return " ".join(value.split()) if isinstance(value, str) else value

    @model_validator(mode="after")
    def _something_changes(self) -> Self:
        if not self.requested:
            raise ValueError(
                f"Name at least one setting to change for campaign {self.campaign.label}."
            )
        start, end = self.start_date, self.end_date
        if isinstance(start, date) and isinstance(end, date) and end < start:
            raise ValueError("The end date must be on or after the start date.")
        return self

    @property
    def resource_name(self) -> str:
        return f"customers/{self.campaign.customer_id}/campaigns/{self.campaign.campaign_id}"

    @property
    def requested(self) -> dict[CampaignSetting, Any]:
        """The settings that change, in card terms: dates as `YYYY-MM-DD`, no end date as null."""
        values: dict[CampaignSetting, Any] = {}
        if self.name is not None:
            values["name"] = self.name
        if self.start_date is not None:
            values["start_date"] = self.start_date.isoformat()
        if self.end_date is not None:
            values["end_date"] = None if self.end_date == "none" else self.end_date.isoformat()
        url = self.url_options
        if url is not None:
            if url.final_url_suffix is not None:
                values["final_url_suffix"] = url.final_url_suffix or None
            if url.tracking_template is not None:
                values["tracking_template"] = url.tracking_template or None
            if url.custom_parameters is not None:
                values["custom_parameters"] = [item.model_dump() for item in url.custom_parameters]
        networks = self.networks
        if networks is not None:
            if networks.search_partners is not None:
                values["search_partners"] = networks.search_partners
            if networks.display_expansion is not None:
                values["display_expansion"] = networks.display_expansion
        return values


class GoogleAdsUpdateCampaignsRequest(GoogleAdsStrictModel):
    """Every argument of a campaign update, so an edited approval is checked whole."""

    changes: list[GoogleAdsCampaignUpdate] = Field(min_length=1, max_length=MAX_CAMPAIGN_UPDATES)

    @model_validator(mode="after")
    def _each_once(self) -> Self:
        names = [change.resource_name for change in self.changes]
        if len(set(names)) != len(names):
            raise ValueError("List each campaign once, with all of its changes.")
        return self


type GoogleAdsSettingValue = str | bool | list[GoogleAdsUrlParameter] | None


class GoogleAdsCampaignSettingOutcome(GoogleAdsStrictModel):
    setting: CampaignSetting
    # As the approval card showed it.
    before: GoogleAdsSettingValue
    requested: GoogleAdsSettingValue
    # Read back after the change; meaningful only when the campaign's `read_back` is true.
    after: GoogleAdsSettingValue
    outcome: Literal["updated", "already_set", "failed", "unverified"]


class GoogleAdsCampaignUpdateOutcome(GoogleAdsStrictModel):
    resource_name: str
    campaign_id: str
    name: str
    read_back: bool
    settings: list[GoogleAdsCampaignSettingOutcome] = Field(max_length=8)
    error_code: str | None = None
    message: str | None = None


class GoogleAdsUpdateCampaignsData(GoogleAdsStrictModel):
    account_id: str
    campaigns: list[GoogleAdsCampaignUpdateOutcome] = Field(max_length=MAX_CAMPAIGN_UPDATES)


class GoogleAdsUpdateCampaignsEntry(IntegrationFanOutEntry):
    data: GoogleAdsUpdateCampaignsData | None = None


class GoogleAdsUpdateCampaignsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsUpdateCampaignsEntry]
