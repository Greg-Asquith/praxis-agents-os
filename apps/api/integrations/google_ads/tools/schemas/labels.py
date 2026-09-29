# apps/api/integrations/google_ads/tools/schemas/labels.py

"""Argument and result contracts for Google Ads label actions."""

from typing import Literal

from pydantic import Field, field_validator

from integrations.google_ads.references import GoogleAdsLabelReference
from integrations.google_ads.references.label import (
    GOOGLE_ADS_LABEL_COLOR_PATTERN,
    GOOGLE_ADS_LABEL_DESCRIPTION_MAX_LENGTH,
    GOOGLE_ADS_LABEL_NAME_MAX_LENGTH,
)
from services.integrations.context.results import (
    IntegrationFanOutEntry,
    IntegrationFanOutOutput,
)

from .base import GoogleAdsStrictModel


class GoogleAdsLabelDraft(GoogleAdsStrictModel):
    name: str = Field(
        min_length=1,
        max_length=GOOGLE_ADS_LABEL_NAME_MAX_LENGTH,
        description="Label name, unique within the account.",
    )
    description: str | None = Field(
        default=None,
        max_length=GOOGLE_ADS_LABEL_DESCRIPTION_MAX_LENGTH,
        description="Optional short description shown with the label.",
    )
    background_color: str | None = Field(
        default=None,
        pattern=GOOGLE_ADS_LABEL_COLOR_PATTERN,
        description="Optional background colour as #RGB or #RRGGBB hex.",
    )

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        return " ".join(value.split()) if isinstance(value, str) else value

    @field_validator("description", "background_color", mode="before")
    @classmethod
    def blank_to_none(cls, value: object) -> object:
        return (value.strip() or None) if isinstance(value, str) else value


class GoogleAdsCreateLabelOutcome(GoogleAdsStrictModel):
    name: str
    description: str | None = None
    background_color: str | None = None
    outcome: Literal["created", "already_exists", "failed", "unverified"]
    reference: GoogleAdsLabelReference | None = None
    error_code: str | None = None
    message: str | None = None


class GoogleAdsCreateLabelsData(GoogleAdsStrictModel):
    labels: list[GoogleAdsCreateLabelOutcome]


class GoogleAdsCreateLabelsEntry(IntegrationFanOutEntry):
    data: GoogleAdsCreateLabelsData | None = None


class GoogleAdsCreateLabelsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsCreateLabelsEntry]
