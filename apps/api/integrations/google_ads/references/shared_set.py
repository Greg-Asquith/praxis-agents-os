# apps/api/integrations/google_ads/references/shared_set.py

import re
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import Field, model_validator

from services.integrations.entity_references import ScopedEntityReference


class GoogleAdsSharedSetReference(ScopedEntityReference):
    entity_kind: Literal["google_ads_shared_set"] = "google_ads_shared_set"
    member_count: int | None = Field(default=None, ge=0)

    @model_validator(mode="before")
    @classmethod
    def canonicalize_shared_set_id(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        normalized = dict(value)
        external_id = _shared_set_id(normalized.get("external_id"))
        if external_id is not None:
            normalized["external_id"] = external_id

        redundant_id = normalized.get("entity_id")
        if (
            external_id is not None
            and redundant_id is not None
            and _shared_set_id(redundant_id) == external_id
        ):
            normalized.pop("entity_id")
        return normalized


def _shared_set_id(value: Any) -> str | None:
    candidate = str(value).strip() if value is not None else ""
    if candidate.isdigit():
        return candidate
    match = re.fullmatch(r"customers/\d+/sharedSets/(\d+)", candidate)
    return match.group(1) if match else None
