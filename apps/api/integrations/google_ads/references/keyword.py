# apps/api/integrations/google_ads/references/keyword.py

"""Reusable Google Ads positive-keyword reference."""

import re
from collections.abc import Mapping
from math import isfinite
from typing import Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_serializer,
    field_validator,
    model_validator,
)

from services.integrations.entity_references import ScopedEntityReference

from ..constants import GOOGLE_ADS_INT64_MAX
from ..operations.url_custom_parameters import validate_url_custom_parameter_items


class GoogleAdsUrlCustomParameter(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    key: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9]+$")
    value: str = Field(max_length=200)


class GoogleAdsKeywordReference(ScopedEntityReference):
    entity_kind: Literal["google_ads_keyword"] = "google_ads_keyword"
    customer_id: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")
    campaign_id: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")
    ad_group_id: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")
    criterion_id: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")
    text: str = Field(min_length=1, max_length=80)
    match_type: Literal["EXACT", "PHRASE", "BROAD"]
    status: Literal["ENABLED", "PAUSED"]
    bid_modifier: float | None = Field(default=None, ge=0.1, le=10)
    cpc_bid_micros: int | None = Field(default=None, ge=0, le=GOOGLE_ADS_INT64_MAX)
    final_urls: list[str] = Field(default_factory=list, max_length=10)
    final_mobile_urls: list[str] = Field(default_factory=list, max_length=10)
    final_url_suffix: str | None = Field(default=None, max_length=2048)
    tracking_url_template: str | None = Field(default=None, max_length=2048)
    url_custom_parameters: list[GoogleAdsUrlCustomParameter] = Field(
        default_factory=list, max_length=8
    )
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
    def serialize_bid_micros(self, value: int | None) -> str | None:
        """Keeps provider int64 money values exact in JSON clients."""
        return str(value) if value is not None else None

    @field_validator("url_custom_parameters")
    @classmethod
    def validate_custom_parameters(
        cls, value: list[GoogleAdsUrlCustomParameter]
    ) -> list[GoogleAdsUrlCustomParameter]:
        validate_url_custom_parameter_items(tuple((item.key, item.value) for item in value))
        return value

    @property
    def provider_scope_id(self) -> str:
        return self.customer_id

    @property
    def provider_entity_id(self) -> str:
        return f"{self.ad_group_id}~{self.criterion_id}"


def positive_keyword_state(reference: GoogleAdsKeywordReference) -> dict[str, Any]:
    """Returns criterion state without display labels or parameter ordering."""
    state = reference.model_dump(mode="json", exclude={"label", "description", "scope_label"})
    state["url_custom_parameters"] = sorted(
        state["url_custom_parameters"], key=lambda item: item["key"]
    )
    return state


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
    if (
        criterion.get("negative", False) is not False
        or criterion.get("type", "KEYWORD") != "KEYWORD"
    ):
        return None
    keyword = criterion.get("keyword")
    if not isinstance(keyword, Mapping):
        return None
    campaign_id = str(campaign.get("id", "")).strip()
    ad_group_id = str(ad_group.get("id", "")).strip()
    criterion_id = str(criterion.get("criterionId", "")).strip()
    resource_name = criterion.get("resourceName")
    if (
        resource_name is not None
        and resource_name != f"customers/{customer_id}/adGroupCriteria/{ad_group_id}~{criterion_id}"
    ):
        return None
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
    raw_bid_modifier = criterion.get("bidModifier")
    if raw_bid_modifier is None:
        bid_modifier = None
    elif (
        isinstance(raw_bid_modifier, int | float)
        and not isinstance(raw_bid_modifier, bool)
        and isfinite(raw_bid_modifier)
    ):
        bid_modifier = raw_bid_modifier
    else:
        return None
    final_urls = _string_list(criterion.get("finalUrls"), maximum=10, max_item_length=2048)
    final_mobile_urls = _string_list(
        criterion.get("finalMobileUrls"), maximum=10, max_item_length=2048
    )
    custom_parameters = _custom_parameters(criterion.get("urlCustomParameters"))
    final_url_suffix_valid, final_url_suffix = _optional_string(criterion.get("finalUrlSuffix"))
    tracking_template_valid, tracking_url_template = _optional_string(
        criterion.get("trackingUrlTemplate")
    )
    if (
        final_urls is None
        or final_mobile_urls is None
        or custom_parameters is None
        or not final_url_suffix_valid
        or not tracking_template_valid
    ):
        return None
    numeric_values = ((criterion.get("cpcBidMicros"), cpc_bid_micros),)
    if any(raw is not None and parsed is None for raw, parsed in numeric_values):
        return None
    try:
        return GoogleAdsKeywordReference(
            customer_id=customer_id,
            campaign_id=campaign_id,
            ad_group_id=ad_group_id,
            criterion_id=criterion_id,
            text=text,
            match_type=match_type,
            status=status,
            bid_modifier=bid_modifier,
            cpc_bid_micros=cpc_bid_micros,
            final_urls=final_urls,
            final_mobile_urls=final_mobile_urls,
            final_url_suffix=final_url_suffix,
            tracking_url_template=tracking_url_template,
            url_custom_parameters=custom_parameters,
            label=text,
            description=f"{match_type.title()} · {status.title()}",
            scope_label=f"{campaign_name[:240]} · {ad_group_name[:240]}",
        )
    except ValidationError:
        return None


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str) and value.isdigit():
        parsed = int(value)
    else:
        return None
    return parsed if 0 <= parsed <= GOOGLE_ADS_INT64_MAX else None


def _string_list(value: Any, *, maximum: int, max_item_length: int) -> list[str] | None:
    if value is None:
        return []
    if (
        not isinstance(value, list)
        or len(value) > maximum
        or not all(
            isinstance(item, str)
            and len(item) <= max_item_length
            and re.fullmatch(r"https?://\S+", item, flags=re.IGNORECASE) is not None
            for item in value
        )
    ):
        return None
    return value


def _custom_parameters(value: Any) -> list[GoogleAdsUrlCustomParameter] | None:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 8:
        return None
    items: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            return None
        key = item.get("key")
        parameter_value = item.get("value")
        if not isinstance(key, str) or not isinstance(parameter_value, str):
            return None
        items.append((key, parameter_value))
    try:
        validated = validate_url_custom_parameter_items(items)
    except ValueError:
        return None
    return [GoogleAdsUrlCustomParameter(key=key, value=item) for key, item in validated]


def _optional_string(value: Any) -> tuple[bool, str | None]:
    if value is None or value == "":
        return True, None
    return (True, value) if isinstance(value, str) else (False, None)
