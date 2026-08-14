# apps/api/integrations/google_ads/references/shared_set.py

import re
from collections.abc import Mapping
from typing import Any, ClassVar, Literal

from pydantic import Field, model_validator

from services.integrations.entity_references import ScopedEntityReference


class GoogleAdsSharedSetReference(ScopedEntityReference):
    entity_kind: Literal["google_ads_shared_set"] = "google_ads_shared_set"
    customer_id: str = Field(
        min_length=1,
        max_length=32,
        pattern=r"^\d+$",
        description="Google Ads customer ID, normalized to digits without hyphens.",
    )
    shared_set_id: str = Field(
        min_length=1,
        max_length=32,
        pattern=r"^\d+$",
        description="Google Ads negative keyword list ID.",
    )
    member_count: int | None = Field(default=None, ge=0)
    identity_fields: ClassVar[tuple[str, ...]] = (
        *ScopedEntityReference.identity_fields,
        "customer_id",
        "shared_set_id",
    )

    @model_validator(mode="before")
    @classmethod
    def canonicalize_shared_set_id(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        normalized = dict(value)
        shared_set_id = _shared_set_id(normalized.get("shared_set_id"))
        if shared_set_id is not None:
            normalized["shared_set_id"] = shared_set_id
        customer_id = normalized.get("customer_id")
        if isinstance(customer_id, str):
            normalized["customer_id"] = customer_id.strip().replace("-", "")
        return normalized

    @property
    def provider_scope_id(self) -> str:
        return self.customer_id

    @property
    def provider_entity_id(self) -> str:
        return self.shared_set_id


def _shared_set_id(value: Any) -> str | None:
    candidate = str(value).strip() if value is not None else ""
    if candidate.isdigit():
        return candidate
    match = re.fullmatch(r"customers/\d+/sharedSets/(\d+)", candidate)
    return match.group(1) if match else None
