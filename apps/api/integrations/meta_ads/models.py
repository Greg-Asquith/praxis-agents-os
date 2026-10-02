# apps/api/integrations/meta_ads/models.py

"""Strict shared models and value types for Meta Ads tools and references."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

type MetaAdsId = Annotated[str, Field(pattern=r"^[0-9]+$", max_length=128)]
type MetaAdsMoney = Annotated[str, Field(max_length=520, pattern=r"^-?[0-9]+(?:\.[0-9]+)?$")]
type MetaAdsText = Annotated[str, Field(max_length=512)]


class MetaAdsStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class MetaAdsObjectBudget(MetaAdsStrictModel):
    kind: Literal["daily", "lifetime", "campaign"]
    amount: MetaAdsMoney | None
    remaining: MetaAdsMoney | None
    # Set only for the campaign kind: whether the campaign budget is daily or lifetime.
    period: Literal["daily", "lifetime"] | None = None


class MetaAdsPromotedObject(MetaAdsStrictModel):
    page_id: MetaAdsId | None = None
    pixel_id: MetaAdsId | None = None
    application_id: MetaAdsId | None = None
    custom_conversion_id: MetaAdsId | None = None
    custom_event_type: MetaAdsText | None = None


class MetaAdsPlacements(MetaAdsStrictModel):
    mode: Literal["automatic", "manual"]
    # Manual placements as platform or platform:position, for example instagram:story.
    positions: list[MetaAdsText] = Field(default_factory=list, max_length=64)
