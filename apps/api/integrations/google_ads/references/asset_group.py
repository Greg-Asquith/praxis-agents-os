# apps/api/integrations/google_ads/references/asset_group.py

from typing import Any, ClassVar, Literal

from pydantic import Field, field_validator

from services.integrations.entity_references import ScopedEntityReference


class GoogleAdsAssetGroupReference(ScopedEntityReference):
    """One Performance Max asset group."""

    entity_kind: Literal["google_ads_asset_group"] = "google_ads_asset_group"
    customer_id: str = Field(
        min_length=1,
        max_length=32,
        pattern=r"^\d+$",
        description="Google Ads customer ID, normalized to digits without hyphens.",
    )
    campaign_id: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")
    asset_group_id: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")
    status: str | None = Field(default=None, max_length=64)
    identity_fields: ClassVar[tuple[str, ...]] = (
        *ScopedEntityReference.identity_fields,
        "customer_id",
        "asset_group_id",
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
        return self.asset_group_id

    @property
    def resource_name(self) -> str:
        return f"customers/{self.customer_id}/assetGroups/{self.asset_group_id}"
