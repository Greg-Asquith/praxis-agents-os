# apps/api/integrations/meta_ads/tools/schemas/targeting.py

"""Targeting options found by name, and Meta's estimated audience for a targeting draft."""

from typing import Literal

from pydantic import Field

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...models import MetaAdsStrictModel, MetaAdsText

MAX_TARGETING_RESULTS = 45

type MetaAdsTargetingKind = Literal[
    "country", "region", "city", "postcode", "interest", "behavior", "demographic", "language"
]


class MetaAdsAudienceSize(MetaAdsStrictModel):
    lower: int = Field(ge=0)
    upper: int = Field(ge=0)


class MetaAdsTargetingOption(MetaAdsStrictModel):
    kind: MetaAdsTargetingKind
    # What a targeting draft takes; the name is for display only.
    key: str = Field(min_length=1, max_length=64)
    name: MetaAdsText
    description: MetaAdsText | None = None
    audience_size_range: MetaAdsAudienceSize | None = None
    country_code: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    region: MetaAdsText | None = None
    # Meta's targeting type, set for demographics.
    category: str | None = Field(default=None, pattern=r"^[a-z_]{1,64}$")


class MetaAdsTargetingSearchData(MetaAdsStrictModel):
    options: list[MetaAdsTargetingOption] = Field(max_length=MAX_TARGETING_RESULTS)
    truncated: bool


class MetaAdsTargetingSearchEntry(IntegrationFanOutEntry):
    data: MetaAdsTargetingSearchData | None = None


class MetaAdsTargetingSearchOutput(IntegrationFanOutOutput):
    results: list[MetaAdsTargetingSearchEntry]


class MetaAdsAudienceEstimateData(MetaAdsStrictModel):
    # Null when Meta has no estimate for this targeting.
    users_lower_bound: int | None = Field(ge=0)
    users_upper_bound: int | None = Field(ge=0)
    notes: list[str] = Field(max_length=2)


class MetaAdsAudienceEstimateEntry(IntegrationFanOutEntry):
    data: MetaAdsAudienceEstimateData | None = None


class MetaAdsAudienceEstimateOutput(IntegrationFanOutOutput):
    results: list[MetaAdsAudienceEstimateEntry]
