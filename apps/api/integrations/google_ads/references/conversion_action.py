# apps/api/integrations/google_ads/references/conversion_action.py

import re
from collections.abc import Mapping
from typing import Any, ClassVar, Literal

from pydantic import Field, model_validator

from services.integrations.entity_references import ScopedEntityReference


class GoogleAdsConversionActionReference(ScopedEntityReference):
    """One conversion action, the `conversionActions/{conversion_action_id}` resource."""

    entity_kind: Literal["google_ads_conversion_action"] = "google_ads_conversion_action"
    customer_id: str = Field(
        min_length=1,
        max_length=32,
        pattern=r"^\d+$",
        description="Google Ads customer ID, normalized to digits without hyphens.",
    )
    conversion_action_id: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")
    identity_fields: ClassVar[tuple[str, ...]] = (
        *ScopedEntityReference.identity_fields,
        "customer_id",
        "conversion_action_id",
    )

    @model_validator(mode="before")
    @classmethod
    def canonicalize_ids(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        normalized = dict(value)
        candidate = str(normalized.get("conversion_action_id") or "").strip()
        match = re.fullmatch(r"customers/\d+/conversionActions/(\d+)", candidate)
        if match:
            normalized["conversion_action_id"] = match.group(1)
        customer_id = normalized.get("customer_id")
        if isinstance(customer_id, str):
            normalized["customer_id"] = customer_id.strip().replace("-", "")
        return normalized

    @property
    def provider_scope_id(self) -> str:
        return self.customer_id

    @property
    def provider_entity_id(self) -> str:
        return self.conversion_action_id

    @property
    def resource_name(self) -> str:
        return f"customers/{self.customer_id}/conversionActions/{self.conversion_action_id}"


class GoogleAdsConversionGoalReference(ScopedEntityReference):
    """One account goal: a conversion category from one origin, such as purchases on the website."""

    entity_kind: Literal["google_ads_conversion_goal"] = "google_ads_conversion_goal"
    customer_id: str = Field(
        min_length=1,
        max_length=32,
        pattern=r"^\d+$",
        description="Google Ads customer ID, normalized to digits without hyphens.",
    )
    # Google's tokens, such as `PURCHASE` and `WEBSITE`.
    category: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")
    origin: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*$")
    identity_fields: ClassVar[tuple[str, ...]] = (
        *ScopedEntityReference.identity_fields,
        "customer_id",
        "category",
        "origin",
    )

    @property
    def provider_scope_id(self) -> str:
        return self.customer_id

    @property
    def provider_entity_id(self) -> str:
        return f"{self.category}~{self.origin}"

    @property
    def resource_name(self) -> str:
        return f"customers/{self.customer_id}/customerConversionGoals/{self.provider_entity_id}"
