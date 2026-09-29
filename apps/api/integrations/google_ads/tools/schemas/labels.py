# apps/api/integrations/google_ads/tools/schemas/labels.py

"""Argument and result contracts for Google Ads label actions."""

from typing import Annotated, Literal

from pydantic import Field, field_validator

from integrations.google_ads.references import (
    GoogleAdsAdGroupReference,
    GoogleAdsCampaignReference,
    GoogleAdsKeywordReference,
    GoogleAdsLabelReference,
)
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


class GoogleAdsCampaignLabelTarget(GoogleAdsStrictModel):
    kind: Literal["campaign"]
    campaign: GoogleAdsCampaignReference


class GoogleAdsAdGroupLabelTarget(GoogleAdsStrictModel):
    kind: Literal["ad_group"]
    ad_group: GoogleAdsAdGroupReference


class GoogleAdsKeywordLabelTarget(GoogleAdsStrictModel):
    kind: Literal["keyword"]
    keyword: GoogleAdsKeywordReference


# A plain alias, since the reference-type walker doesn't unwrap `type` statements.
GoogleAdsLabelTarget = Annotated[
    GoogleAdsCampaignLabelTarget | GoogleAdsAdGroupLabelTarget | GoogleAdsKeywordLabelTarget,
    Field(discriminator="kind"),
]


class GoogleAdsLabelAssociationOutcome(GoogleAdsStrictModel):
    label_id: str
    label_name: str
    label_color: str | None = None
    target_kind: Literal["campaign", "ad_group", "keyword"]
    target_id: str
    target_name: str
    error_code: str | None = None
    message: str | None = None


class GoogleAdsApplyLabelOutcome(GoogleAdsLabelAssociationOutcome):
    outcome: Literal["applied", "already_applied", "failed", "unverified"]


class GoogleAdsRemoveLabelOutcome(GoogleAdsLabelAssociationOutcome):
    outcome: Literal["removed", "not_applied", "failed", "unverified"]


class GoogleAdsApplyLabelsData(GoogleAdsStrictModel):
    associations: list[GoogleAdsApplyLabelOutcome]


class GoogleAdsRemoveLabelsData(GoogleAdsStrictModel):
    associations: list[GoogleAdsRemoveLabelOutcome]


class GoogleAdsApplyLabelsEntry(IntegrationFanOutEntry):
    data: GoogleAdsApplyLabelsData | None = None


class GoogleAdsRemoveLabelsEntry(IntegrationFanOutEntry):
    data: GoogleAdsRemoveLabelsData | None = None


class GoogleAdsApplyLabelsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsApplyLabelsEntry]


class GoogleAdsRemoveLabelsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsRemoveLabelsEntry]
