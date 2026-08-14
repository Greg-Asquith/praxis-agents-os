# apps/api/integrations/google_ads/references/ad_group.py

from typing import Any, ClassVar, Literal

from pydantic import Field, field_validator

from services.integrations.entity_references import ScopedEntityReference


class GoogleAdsAdGroupReference(ScopedEntityReference):
    entity_kind: Literal["google_ads_ad_group"] = "google_ads_ad_group"
    customer_id: str = Field(
        min_length=1,
        max_length=32,
        pattern=r"^\d+$",
        description="Google Ads customer ID, normalized to digits without hyphens.",
    )
    campaign_id: str = Field(
        min_length=1,
        max_length=32,
        pattern=r"^\d+$",
        description="Google Ads parent campaign ID.",
    )
    ad_group_id: str = Field(
        min_length=1,
        max_length=32,
        pattern=r"^\d+$",
        description="Google Ads ad group ID.",
    )
    status: str | None = Field(default=None, max_length=64)
    identity_fields: ClassVar[tuple[str, ...]] = (
        *ScopedEntityReference.identity_fields,
        "customer_id",
        "campaign_id",
        "ad_group_id",
    )

    @field_validator("customer_id", mode="before")
    @classmethod
    def normalize_customer_id(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().replace("-", "")
        return value

    @property
    def provider_scope_id(self) -> str:
        return self.customer_id

    @property
    def provider_entity_id(self) -> str:
        return self.ad_group_id
