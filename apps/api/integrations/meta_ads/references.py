# apps/api/integrations/meta_ads/references.py

"""Scoped references to campaigns, ad sets, and ads in one selected ad account."""

from typing import ClassVar, Literal

from pydantic import Field

from services.integrations.entity_references import ScopedEntityReference

from .models import (
    MetaAdsId,
    MetaAdsObjectBudget,
    MetaAdsPlacements,
    MetaAdsPromotedObject,
    MetaAdsText,
)


class _MetaAdsObjectReference(ScopedEntityReference):
    account_id: MetaAdsId = Field(description="Meta ad account ID, digits only.")
    status: MetaAdsText | None = None
    effective_status: MetaAdsText | None = None

    identity_fields: ClassVar[tuple[str, ...]] = (
        *ScopedEntityReference.identity_fields,
        "account_id",
    )

    @property
    def provider_scope_id(self) -> str:
        return self.account_id


class MetaAdsCampaignReference(_MetaAdsObjectReference):
    entity_kind: Literal["meta_ads_campaign"] = "meta_ads_campaign"
    campaign_id: MetaAdsId = Field(description="Meta campaign ID.")
    objective: MetaAdsText | None = None
    # Null when each ad set holds its own budget.
    budget: MetaAdsObjectBudget | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")

    identity_fields: ClassVar[tuple[str, ...]] = (
        *_MetaAdsObjectReference.identity_fields,
        "campaign_id",
    )

    @property
    def provider_entity_id(self) -> str:
        return self.campaign_id


class MetaAdsAdSetReference(_MetaAdsObjectReference):
    """Ad set with the delivery settings ad creation validates before approval."""

    entity_kind: Literal["meta_ads_ad_set"] = "meta_ads_ad_set"
    campaign_id: MetaAdsId = Field(description="Meta parent campaign ID.")
    adset_id: MetaAdsId = Field(description="Meta ad set ID.")
    objective: MetaAdsText | None = None
    optimization_goal: MetaAdsText | None = None
    destination_type: MetaAdsText | None = None
    promoted_object: MetaAdsPromotedObject | None = None
    placements: MetaAdsPlacements | None = None
    is_dynamic_creative: bool | None = None
    # Kind `campaign` means the parent campaign holds the budget.
    budget: MetaAdsObjectBudget | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")

    identity_fields: ClassVar[tuple[str, ...]] = (
        *_MetaAdsObjectReference.identity_fields,
        "adset_id",
    )

    @property
    def provider_entity_id(self) -> str:
        return self.adset_id


class MetaAdsAdReference(_MetaAdsObjectReference):
    entity_kind: Literal["meta_ads_ad"] = "meta_ads_ad"
    campaign_id: MetaAdsId = Field(description="Meta parent campaign ID.")
    adset_id: MetaAdsId = Field(description="Meta parent ad set ID.")
    ad_id: MetaAdsId = Field(description="Meta ad ID.")

    identity_fields: ClassVar[tuple[str, ...]] = (
        *_MetaAdsObjectReference.identity_fields,
        "ad_id",
    )

    @property
    def provider_entity_id(self) -> str:
        return self.ad_id


type MetaAdsObjectReference = MetaAdsCampaignReference | MetaAdsAdSetReference | MetaAdsAdReference
