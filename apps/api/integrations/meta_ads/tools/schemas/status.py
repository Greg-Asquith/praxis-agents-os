# apps/api/integrations/meta_ads/tools/schemas/status.py

"""Approval and result contracts for turning Meta campaigns, ad sets, and ads on or off."""

from typing import Any, Literal, Self

from pydantic import BaseModel, Field, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...models import MetaAdsId, MetaAdsStrictModel, MetaAdsText
from .objects import MetaAdsObjectType


class MetaAdsStatusSelection(BaseModel):
    """Bounds an edited approval before review: 1 to 50 objects across optional lists."""

    status: Literal["ACTIVE", "PAUSED"]
    campaigns: list[dict[str, Any]] | None = Field(default=None, min_length=1)
    ad_sets: list[dict[str, Any]] | None = Field(default=None, min_length=1)
    ads: list[dict[str, Any]] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _check_total(self) -> Self:
        total = sum(len(items or ()) for items in (self.campaigns, self.ad_sets, self.ads))
        if not 1 <= total <= 50:
            raise ValueError("Choose between 1 and 50 Meta Ads objects.")
        return self


class MetaAdsStatusOutcome(MetaAdsStrictModel):
    object_type: MetaAdsObjectType
    object_id: MetaAdsId
    object_name: MetaAdsText | None
    campaign_id: MetaAdsId | None
    adset_id: MetaAdsId | None
    previous_status: MetaAdsText | None
    previous_effective_status: MetaAdsText | None
    # Read back after the change; null when the object couldn't be read.
    status: MetaAdsText | None
    effective_status: MetaAdsText | None
    outcome: Literal["updated", "already_set", "failed", "unverified"]
    error_code: str | None = Field(default=None, max_length=100)
    message: str | None = Field(default=None, max_length=1000)


class MetaAdsStatusData(MetaAdsStrictModel):
    account_id: MetaAdsId
    requested_status: Literal["ACTIVE", "PAUSED"]
    objects: list[MetaAdsStatusOutcome] = Field(max_length=50)


class MetaAdsStatusEntry(IntegrationFanOutEntry):
    data: MetaAdsStatusData | None = None


class MetaAdsStatusOutput(IntegrationFanOutOutput):
    results: list[MetaAdsStatusEntry]
