# apps/api/integrations/google_ads/references/asset.py

import re
from collections.abc import Mapping
from typing import Any, ClassVar, Literal

from pydantic import Field, model_validator

from services.integrations.entity_references import ScopedEntityReference

# The asset types the asset tools take, in Google's names.
type GoogleAdsAssetType = Literal["SITELINK", "CALLOUT"]


class GoogleAdsAssetReference(ScopedEntityReference):
    """One account asset, such as a sitelink, the `assets/{asset_id}` resource."""

    entity_kind: Literal["google_ads_asset"] = "google_ads_asset"
    customer_id: str = Field(
        min_length=1,
        max_length=32,
        pattern=r"^\d+$",
        description="Google Ads customer ID, normalized to digits without hyphens.",
    )
    asset_id: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")
    asset_type: GoogleAdsAssetType
    identity_fields: ClassVar[tuple[str, ...]] = (
        *ScopedEntityReference.identity_fields,
        "customer_id",
        "asset_id",
    )

    @model_validator(mode="before")
    @classmethod
    def canonicalize_ids(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        normalized = dict(value)
        candidate = str(normalized.get("asset_id") or "").strip()
        match = re.fullmatch(r"customers/\d+/assets/(\d+)", candidate)
        if match:
            normalized["asset_id"] = match.group(1)
        customer_id = normalized.get("customer_id")
        if isinstance(customer_id, str):
            normalized["customer_id"] = customer_id.strip().replace("-", "")
        return normalized

    @property
    def provider_scope_id(self) -> str:
        return self.customer_id

    @property
    def provider_entity_id(self) -> str:
        return self.asset_id

    @property
    def resource_name(self) -> str:
        return f"customers/{self.customer_id}/assets/{self.asset_id}"
