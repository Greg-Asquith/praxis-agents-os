# apps/api/integrations/google_ads/references/keyword.py

"""Reusable Google Ads positive-keyword reference."""

import re
from collections.abc import Mapping
from typing import Any, ClassVar, Literal

from pydantic import Field, field_serializer, model_validator

from services.integrations.entity_references import ScopedEntityReference

from ..constants import GOOGLE_ADS_INT64_MAX


class GoogleAdsKeywordReference(ScopedEntityReference):
    entity_kind: Literal["google_ads_keyword"] = "google_ads_keyword"
    customer_id: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")
    campaign_id: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")
    ad_group_id: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")
    criterion_id: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")
    text: str = Field(min_length=1, max_length=80)
    match_type: Literal["EXACT", "PHRASE", "BROAD"]
    status: Literal["ENABLED", "PAUSED"]
    cpc_bid_micros: int | None = Field(default=None, ge=0, le=GOOGLE_ADS_INT64_MAX)
    identity_fields: ClassVar[tuple[str, ...]] = (
        *ScopedEntityReference.identity_fields,
        "customer_id",
        "ad_group_id",
        "criterion_id",
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
        criterion_id, ad_group_id, resource_customer_id = _criterion_identity(
            normalized.get("criterion_id")
        )
        if resource_customer_id is not None and resource_customer_id != normalized.get(
            "customer_id"
        ):
            raise ValueError("Keyword resource name must belong to its customer")
        if ad_group_id is not None and ad_group_id != normalized.get("ad_group_id"):
            raise ValueError("Keyword resource name must belong to its ad group")
        if criterion_id is not None:
            normalized["criterion_id"] = criterion_id
        return normalized

    @field_serializer("cpc_bid_micros", when_used="json")
    def serialize_cpc_bid_micros(self, value: int | None) -> str | None:
        """Keeps provider int64 money values exact in JSON clients."""
        return str(value) if value is not None else None

    @property
    def provider_scope_id(self) -> str:
        return self.customer_id

    @property
    def provider_entity_id(self) -> str:
        return f"{self.ad_group_id}~{self.criterion_id}"


def _criterion_identity(value: Any) -> tuple[str | None, str | None, str | None]:
    candidate = str(value).strip() if value is not None else ""
    if candidate.isdigit():
        return candidate, None, None
    match = re.fullmatch(r"customers/(\d+)/adGroupCriteria/(\d+)~(\d+)", candidate)
    return (match.group(3), match.group(2), match.group(1)) if match else (None, None, None)


def positive_keyword_reference_from_row(
    customer_id: str,
    row: Mapping[str, Any],
) -> GoogleAdsKeywordReference | None:
    """Build a positive-keyword reference from one provider result row."""
    campaign = row.get("campaign")
    ad_group = row.get("adGroup")
    criterion = row.get("adGroupCriterion")
    if not all(isinstance(value, Mapping) for value in (campaign, ad_group, criterion)):
        return None
    keyword = criterion.get("keyword")
    if not isinstance(keyword, Mapping):
        return None
    campaign_id = str(campaign.get("id", "")).strip()
    ad_group_id = str(ad_group.get("id", "")).strip()
    criterion_id = str(criterion.get("criterionId", "")).strip()
    text = str(keyword.get("text", "")).strip()
    match_type = str(keyword.get("matchType", "")).strip()
    status = str(criterion.get("status", "")).strip()
    if (
        not campaign_id.isdigit()
        or not ad_group_id.isdigit()
        or not criterion_id.isdigit()
        or not text
        or match_type not in {"EXACT", "PHRASE", "BROAD"}
        or status not in {"ENABLED", "PAUSED"}
    ):
        return None
    campaign_name = str(campaign.get("name", "")).strip() or "(unnamed campaign)"
    ad_group_name = str(ad_group.get("name", "")).strip() or "(unnamed ad group)"
    cpc_bid_micros = _nonnegative_int(criterion.get("cpcBidMicros"))
    return GoogleAdsKeywordReference(
        customer_id=customer_id,
        campaign_id=campaign_id,
        ad_group_id=ad_group_id,
        criterion_id=criterion_id,
        text=text,
        match_type=match_type,
        status=status,
        cpc_bid_micros=cpc_bid_micros,
        label=text,
        description=f"{match_type.title()} · {status.title()}",
        scope_label=f"{campaign_name[:240]} · {ad_group_name[:240]}",
    )


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if 0 <= parsed <= GOOGLE_ADS_INT64_MAX else None
