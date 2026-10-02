# apps/api/integrations/meta_ads/tools/schemas/conversions.py

"""Typed account-scoped custom conversions and custom events."""

from typing import Literal, Self

from pydantic import Field, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...models import MetaAdsId, MetaAdsStrictModel, MetaAdsText

CUSTOM_CONVERSIONS_MAX_ROWS = 500
# Insights action types: custom conversions by ID, pixel custom events by name.
CUSTOM_CONVERSION_PREFIX = "offsite_conversion.custom."
CUSTOM_EVENT_PREFIX = "offsite_conversion.fb_pixel_custom."


class MetaAdsConversion(MetaAdsStrictModel):
    kind: Literal["custom_conversion", "custom_event"]
    action_type: str = Field(max_length=256)
    id: MetaAdsId | None = None
    name: MetaAdsText | None = None
    description: MetaAdsText | None = None
    is_archived: bool | None = Field(default=None, strict=True)
    is_unavailable: bool | None = Field(default=None, strict=True)
    recent_conversions: float | None = None

    @model_validator(mode="after")
    def _matches_action_type(self) -> Self:
        # Insights reports custom conversions by ID and custom events by name.
        if self.kind == "custom_conversion":
            valid = (
                self.id is not None and self.action_type == f"{CUSTOM_CONVERSION_PREFIX}{self.id}"
            )
        else:
            valid = (
                self.id is None
                and bool(self.name)
                and self.action_type == f"{CUSTOM_EVENT_PREFIX}{self.name}"
            )
        if not valid:
            raise ValueError("Conversion identity does not match its action type.")
        return self


class MetaAdsConversionsData(MetaAdsStrictModel):
    conversions: list[MetaAdsConversion]
    conversion_count: int = Field(ge=0)
    truncated: bool
    notes: list[str]
    recent_since: str | None = None
    recent_until: str | None = None


class MetaAdsConversionsEntry(IntegrationFanOutEntry):
    data: MetaAdsConversionsData | None = None


class MetaAdsConversionsOutput(IntegrationFanOutOutput):
    results: list[MetaAdsConversionsEntry]
