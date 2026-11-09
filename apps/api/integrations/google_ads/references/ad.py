# apps/api/integrations/google_ads/references/ad.py

from typing import Any, ClassVar, Literal

from pydantic import Field, field_validator

from services.integrations.entity_references import ScopedEntityReference


class GoogleAdsAdReference(ScopedEntityReference):
    """One ad in one ad group, the `adGroupAds/{ad_group_id}~{ad_id}` resource."""

    entity_kind: Literal["google_ads_ad"] = "google_ads_ad"
    customer_id: str = Field(
        min_length=1,
        max_length=32,
        pattern=r"^\d+$",
        description="Google Ads customer ID, normalized to digits without hyphens.",
    )
    campaign_id: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")
    ad_group_id: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")
    ad_id: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")
    status: str | None = Field(default=None, max_length=64)
    identity_fields: ClassVar[tuple[str, ...]] = (
        *ScopedEntityReference.identity_fields,
        "customer_id",
        "ad_group_id",
        "ad_id",
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
        return f"{self.ad_group_id}~{self.ad_id}"

    @property
    def resource_name(self) -> str:
        return f"customers/{self.customer_id}/adGroupAds/{self.ad_group_id}~{self.ad_id}"
