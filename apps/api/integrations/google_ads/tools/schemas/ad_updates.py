# apps/api/integrations/google_ads/tools/schemas/ad_updates.py

"""Arguments and result contract for editing the copy of live responsive search ads."""

from typing import Annotated, Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...references import GoogleAdsAdReference
from .ads import (
    GoogleAdsDescription,
    GoogleAdsDescriptionPin,
    GoogleAdsHeadline,
    GoogleAdsHeadlinePin,
)
from .base import GoogleAdsStrictModel
from .positive_keywords import GoogleAdsFinalUrl

MAX_AD_UPDATES = 50

type _RemovedText = Annotated[str, Field(min_length=1, max_length=90)]


class GoogleAdsAssetPin(GoogleAdsStrictModel):
    """Pins the headline or description with this text, or unpins it when `pin` is null."""

    text: str = Field(min_length=1, max_length=90)
    pin: GoogleAdsHeadlinePin | GoogleAdsDescriptionPin | None

    @field_validator("text", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class GoogleAdsAdUpdate(GoogleAdsStrictModel):
    """One responsive search ad and only the edits to make to it."""

    ad: GoogleAdsAdReference
    add_headlines: list[GoogleAdsHeadline] | None = Field(default=None, max_length=15)
    remove_headlines: list[_RemovedText] | None = Field(default=None, max_length=15)
    add_descriptions: list[GoogleAdsDescription] | None = Field(default=None, max_length=4)
    remove_descriptions: list[_RemovedText] | None = Field(default=None, max_length=4)
    pins: list[GoogleAdsAssetPin] | None = Field(default=None, max_length=19)
    # An empty path clears it.
    path1: str | None = Field(default=None, max_length=15)
    path2: str | None = Field(default=None, max_length=15)
    final_url: GoogleAdsFinalUrl | None = None

    @field_validator("remove_headlines", "remove_descriptions", mode="before")
    @classmethod
    def _strip_texts(cls, value: object) -> object:
        if isinstance(value, list):
            return [item.strip() if isinstance(item, str) else item for item in value]
        return value

    @field_validator("path1", "path2", mode="before")
    @classmethod
    def _strip_path(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _something_changes(self) -> Self:
        if not self.requested:
            raise ValueError(f"Name at least one edit for ad {self.ad.label}.")
        return self

    @property
    def requested(self) -> dict[str, Any]:
        """The edits in card terms, leaving out what the entry doesn't name."""
        values = self.model_dump(mode="json", exclude={"ad"}, exclude_none=True)
        for key in ("add_headlines", "add_descriptions"):
            if key in values:
                values[key] = [
                    {"text": item["text"], "pin": item.get("pin")} for item in values[key]
                ]
        if "pins" in values:
            values["pins"] = [
                {"text": item["text"], "pin": item.get("pin")} for item in values["pins"]
            ]
        return {key: value for key, value in values.items() if value != []}


class GoogleAdsUpdateAdsRequest(GoogleAdsStrictModel):
    """Every argument of an ad update, so an edited approval is checked whole."""

    changes: list[GoogleAdsAdUpdate] = Field(min_length=1, max_length=MAX_AD_UPDATES)

    @model_validator(mode="after")
    def _each_once(self) -> Self:
        ids = [(change.ad.customer_id, change.ad.ad_id) for change in self.changes]
        if len(set(ids)) != len(ids):
            raise ValueError("List each ad once, with all of its edits.")
        return self


class GoogleAdsTextAssetValue(GoogleAdsStrictModel):
    text: str = Field(max_length=90)
    pin: str | None = Field(default=None, max_length=32)


class GoogleAdsAdCopyValue(GoogleAdsStrictModel):
    headlines: list[GoogleAdsTextAssetValue] = Field(max_length=15)
    descriptions: list[GoogleAdsTextAssetValue] = Field(max_length=4)
    path1: str | None = Field(default=None, max_length=15)
    path2: str | None = Field(default=None, max_length=15)
    final_url: str | None = Field(default=None, max_length=2048)


class GoogleAdsAdUpdateOutcome(GoogleAdsStrictModel):
    resource_name: str
    ad_id: str
    name: str
    ad_group_name: str
    campaign_name: str
    # As the approval card showed it, and as requested after the merge.
    before: GoogleAdsAdCopyValue | None
    requested: GoogleAdsAdCopyValue | None
    # Read back after the change; null when the read failed or nothing changed.
    after: GoogleAdsAdCopyValue | None
    outcome: Literal["updated", "already_set", "failed", "unverified"]
    # Google's policy review, read back after the change.
    review_status: str | None = None
    approval_status: str | None = None
    error_code: str | None = None
    message: str | None = None


class GoogleAdsUpdateAdsData(GoogleAdsStrictModel):
    account_id: str
    ads: list[GoogleAdsAdUpdateOutcome] = Field(max_length=MAX_AD_UPDATES)


class GoogleAdsUpdateAdsEntry(IntegrationFanOutEntry):
    data: GoogleAdsUpdateAdsData | None = None


class GoogleAdsUpdateAdsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsUpdateAdsEntry]
