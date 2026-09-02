# apps/api/integrations/google_ads/references/campaign_budget.py

"""Reusable Google Ads campaign budget reference."""

import re
from collections.abc import Mapping
from typing import Any, ClassVar, Literal

from pydantic import Field, model_validator

from services.integrations.entity_references import ScopedEntityReference


class GoogleAdsCampaignBudgetReference(ScopedEntityReference):
    entity_kind: Literal["google_ads_campaign_budget"] = "google_ads_campaign_budget"
    customer_id: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")
    budget_id: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")
    status: str | None = Field(default=None, max_length=64)
    period: str | None = Field(default=None, max_length=64)
    delivery_method: str | None = Field(default=None, max_length=64)
    amount_micros: int | None = Field(default=None, ge=0)
    total_amount_micros: int | None = Field(default=None, ge=0)
    explicitly_shared: bool | None = None
    reference_count: int | None = Field(default=None, ge=0)
    currency_code: str | None = Field(default=None, max_length=16)
    campaign_labels: tuple[str, ...] = Field(default=(), max_length=50)
    identity_fields: ClassVar[tuple[str, ...]] = (
        *ScopedEntityReference.identity_fields,
        "customer_id",
        "budget_id",
    )

    @model_validator(mode="before")
    @classmethod
    def canonicalize_ids(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        normalized = dict(value)
        customer_id = normalized.get("customer_id")
        if isinstance(customer_id, str):
            normalized["customer_id"] = customer_id.strip().replace("-", "")
        budget_id, resource_customer_id = _budget_identity(normalized.get("budget_id"))
        if resource_customer_id is not None and resource_customer_id != normalized.get(
            "customer_id"
        ):
            raise ValueError("Campaign budget resource name must belong to its customer")
        if budget_id is not None:
            normalized["budget_id"] = budget_id
        return normalized

    @property
    def provider_scope_id(self) -> str:
        return self.customer_id

    @property
    def provider_entity_id(self) -> str:
        return self.budget_id


def _budget_identity(value: Any) -> tuple[str | None, str | None]:
    candidate = str(value).strip() if value is not None else ""
    if candidate.isdigit():
        return candidate, None
    match = re.fullmatch(r"customers/(\d+)/campaignBudgets/(\d+)", candidate)
    return (match.group(2), match.group(1)) if match else (None, None)
