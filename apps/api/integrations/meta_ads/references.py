# apps/api/integrations/meta_ads/references.py

"""Scoped references to objects, media, and identities in one selected ad account."""

from typing import ClassVar, Literal, Self

from pydantic import Field, model_validator

from services.integrations.entity_references import ScopedEntityReference

from .models import (
    MetaAdsId,
    MetaAdsImageHash,
    MetaAdsMediaStatus,
    MetaAdsMediaType,
    MetaAdsMediaUrl,
    MetaAdsObjectBudget,
    MetaAdsPlacements,
    MetaAdsPromotedObject,
    MetaAdsText,
)


class _MetaAdsAccountReference(ScopedEntityReference):
    account_id: MetaAdsId = Field(description="Meta ad account ID, digits only.")

    identity_fields: ClassVar[tuple[str, ...]] = (
        *ScopedEntityReference.identity_fields,
        "account_id",
    )

    @property
    def provider_scope_id(self) -> str:
        return self.account_id


class _MetaAdsObjectReference(_MetaAdsAccountReference):
    status: MetaAdsText | None = None
    effective_status: MetaAdsText | None = None


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


class MetaAdsMediaReference(_MetaAdsAccountReference):
    """Image or video in one ad account's media library."""

    entity_kind: Literal["meta_ads_media"] = "meta_ads_media"
    media_type: MetaAdsMediaType
    image_hash: MetaAdsImageHash | None = Field(default=None, description="Set for images.")
    video_id: MetaAdsId | None = Field(default=None, description="Set for videos.")
    width: int | None = Field(default=None, ge=1, le=100_000)
    height: int | None = Field(default=None, ge=1, le=100_000)
    media_status: MetaAdsMediaStatus | None = None
    thumbnail_url: MetaAdsMediaUrl | None = None

    identity_fields: ClassVar[tuple[str, ...]] = (
        *_MetaAdsAccountReference.identity_fields,
        "media_type",
        "image_hash",
        "video_id",
    )

    @model_validator(mode="after")
    def _one_media_id(self) -> Self:
        image = self.media_type == "image"
        if (self.image_hash is None) == image or (self.video_id is None) != image:
            raise ValueError("Images need image_hash and videos need video_id.")
        return self

    @property
    def provider_entity_id(self) -> str:
        return self.image_hash or self.video_id or ""


class MetaAdsPageReference(_MetaAdsAccountReference):
    """Facebook Page that the ad account can advertise as."""

    entity_kind: Literal["meta_ads_page"] = "meta_ads_page"
    page_id: MetaAdsId = Field(description="Facebook Page ID.")
    picture_url: MetaAdsMediaUrl | None = None

    identity_fields: ClassVar[tuple[str, ...]] = (
        *_MetaAdsAccountReference.identity_fields,
        "page_id",
    )

    @property
    def provider_entity_id(self) -> str:
        return self.page_id


class MetaAdsInstagramAccountReference(_MetaAdsAccountReference):
    """Instagram account connected to the ad account."""

    entity_kind: Literal["meta_ads_instagram_account"] = "meta_ads_instagram_account"
    instagram_user_id: MetaAdsId = Field(description="Instagram user ID used in ad creatives.")
    username: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._]{1,30}$")
    picture_url: MetaAdsMediaUrl | None = None
    # The ad account's edge doesn't say which Page the account belongs to.
    page_id: MetaAdsId | None = None

    identity_fields: ClassVar[tuple[str, ...]] = (
        *_MetaAdsAccountReference.identity_fields,
        "instagram_user_id",
    )

    @property
    def provider_entity_id(self) -> str:
        return self.instagram_user_id


type MetaAdsObjectReference = MetaAdsCampaignReference | MetaAdsAdSetReference | MetaAdsAdReference
