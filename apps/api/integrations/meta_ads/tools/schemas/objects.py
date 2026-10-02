# apps/api/integrations/meta_ads/tools/schemas/objects.py

"""Bounded filters and typed Meta advertising objects."""

from typing import Literal, get_args

from pydantic import Field, model_validator

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from ...models import (
    MetaAdsId,
    MetaAdsMoney,
    MetaAdsObjectBudget,
    MetaAdsPlacements,
    MetaAdsPromotedObject,
    MetaAdsStrictModel,
    MetaAdsText,
)

type MetaAdsObjectType = Literal["campaign", "adset", "ad"]
type MetaAdsCampaignStatus = Literal[
    "ACTIVE", "PAUSED", "ARCHIVED", "DELETED", "IN_PROCESS", "WITH_ISSUES"
]
type MetaAdsAdsetStatus = Literal[
    "ACTIVE", "PAUSED", "ARCHIVED", "DELETED", "IN_PROCESS", "WITH_ISSUES", "CAMPAIGN_PAUSED"
]
type MetaAdsAdStatus = Literal[
    "ACTIVE",
    "PAUSED",
    "ARCHIVED",
    "DELETED",
    "IN_PROCESS",
    "WITH_ISSUES",
    "CAMPAIGN_PAUSED",
    "ADSET_PAUSED",
    "DISAPPROVED",
    "PENDING_BILLING_INFO",
    "PENDING_REVIEW",
    "PREAPPROVED",
]

OBJECT_STATUSES = {
    "campaign": get_args(MetaAdsCampaignStatus.__value__),
    "adset": get_args(MetaAdsAdsetStatus.__value__),
    "ad": get_args(MetaAdsAdStatus.__value__),
}
DEFAULT_STATUSES = {
    "campaign": ["ACTIVE", "PAUSED"],
    "adset": ["ACTIVE", "PAUSED", "CAMPAIGN_PAUSED"],
    "ad": ["ACTIVE", "PAUSED", "CAMPAIGN_PAUSED", "ADSET_PAUSED"],
}


class MetaAdsObjectsInput(MetaAdsStrictModel):
    object_type: MetaAdsObjectType
    statuses: list[MetaAdsAdStatus] | None = Field(default=None, min_length=1, max_length=12)
    campaign_ids: list[MetaAdsId] | None = Field(default=None, min_length=1, max_length=50)
    adset_ids: list[MetaAdsId] | None = Field(default=None, min_length=1, max_length=50)
    name_contains: str | None = Field(default=None, min_length=1, max_length=512)
    limit: int = Field(default=100, strict=True, ge=1, le=500)

    @model_validator(mode="after")
    def validate_filters(self) -> "MetaAdsObjectsInput":
        if self.statuses and any(
            item not in OBJECT_STATUSES[self.object_type] for item in self.statuses
        ):
            raise ValueError("statuses contains a delivery status unsupported for object_type.")
        if self.campaign_ids and self.object_type == "campaign":
            raise ValueError("campaign_ids only filters ad sets and ads.")
        if self.adset_ids and self.object_type != "ad":
            raise ValueError("adset_ids only filters ads.")
        return self


class MetaAdsObject(MetaAdsStrictModel):
    id: MetaAdsId
    name: MetaAdsText | None
    status: MetaAdsText | None
    effective_status: MetaAdsText | None
    objective: MetaAdsText | None
    optimization_goal: MetaAdsText | None
    bid_strategy: MetaAdsText | None
    budget: MetaAdsObjectBudget | None
    bid_amount: MetaAdsMoney | None
    start_time: MetaAdsText | None
    end_time: MetaAdsText | None
    campaign_id: MetaAdsId | None
    adset_id: MetaAdsId | None
    destination_type: MetaAdsText | None = None
    promoted_object: MetaAdsPromotedObject | None = None
    placements: MetaAdsPlacements | None = None
    is_dynamic_creative: bool | None = None


class MetaAdsObjectsData(MetaAdsStrictModel):
    object_type: MetaAdsObjectType
    objects: list[MetaAdsObject]
    object_count: int = Field(ge=0)
    truncated: bool
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class MetaAdsObjectsEntry(IntegrationFanOutEntry):
    data: MetaAdsObjectsData | None = None


class MetaAdsObjectsOutput(IntegrationFanOutOutput):
    results: list[MetaAdsObjectsEntry]
