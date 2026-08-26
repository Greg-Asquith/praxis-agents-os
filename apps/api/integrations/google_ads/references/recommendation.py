# apps/api/integrations/google_ads/references/recommendation.py

"""Provider-owned reference to one Google Ads recommendation."""

from typing import Any, ClassVar, Literal

from pydantic import Field, field_validator, model_validator

from services.integrations.entity_references import ScopedEntityReference

from ..recommendation_utils import recommendation_customer_id


class GoogleAdsRecommendationReference(ScopedEntityReference):
    entity_kind: Literal["google_ads_recommendation"] = "google_ads_recommendation"
    customer_id: str = Field(
        min_length=1,
        max_length=32,
        pattern=r"^\d+$",
        description="Google Ads customer ID, normalized to digits without hyphens.",
    )
    resource_name: str = Field(
        min_length=1,
        max_length=320,
        description="Google Ads recommendation resource name.",
    )
    recommendation_type: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Z][A-Z0-9_]*$",
        description="Google Ads recommendation type returned by the provider.",
    )
    identity_fields: ClassVar[tuple[str, ...]] = (
        *ScopedEntityReference.identity_fields,
        "customer_id",
        "resource_name",
        "recommendation_type",
    )

    @field_validator("customer_id", mode="before")
    @classmethod
    def normalize_customer_id(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().replace("-", "")
        return value

    @model_validator(mode="after")
    def validate_resource_scope(self) -> "GoogleAdsRecommendationReference":
        if recommendation_customer_id(self.resource_name) != self.customer_id:
            raise ValueError("Recommendation resource name must belong to its customer")
        return self

    @property
    def provider_scope_id(self) -> str:
        return self.customer_id

    @property
    def provider_entity_id(self) -> str:
        return self.resource_name
