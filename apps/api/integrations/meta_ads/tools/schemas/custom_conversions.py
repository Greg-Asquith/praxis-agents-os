# apps/api/integrations/meta_ads/tools/schemas/custom_conversions.py

"""Typed account-scoped custom conversion metadata."""

from pydantic import Field

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from .base import MetaAdsId, MetaAdsStrictModel, MetaAdsText

CUSTOM_CONVERSIONS_MAX_ROWS = 500


class MetaAdsCustomConversion(MetaAdsStrictModel):
    id: MetaAdsId
    name: MetaAdsText | None = None
    description: MetaAdsText | None = None
    is_archived: bool | None = Field(default=None, strict=True)
    is_unavailable: bool | None = Field(default=None, strict=True)


class MetaAdsCustomConversionsData(MetaAdsStrictModel):
    conversions: list[MetaAdsCustomConversion]
    conversion_count: int = Field(ge=0)
    truncated: bool
    notes: list[str]


class MetaAdsCustomConversionsEntry(IntegrationFanOutEntry):
    data: MetaAdsCustomConversionsData | None = None


class MetaAdsCustomConversionsOutput(IntegrationFanOutOutput):
    results: list[MetaAdsCustomConversionsEntry]
