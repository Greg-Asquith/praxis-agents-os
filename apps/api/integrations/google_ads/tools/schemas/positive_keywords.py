# apps/api/integrations/google_ads/tools/schemas/positive_keywords.py

"""Input and result contracts for Google Ads positive-keyword actions."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, field_validator, model_validator

from integrations.google_ads.constants import GOOGLE_ADS_INT64_MAX
from integrations.google_ads.references import GoogleAdsKeywordReference
from integrations.google_ads.references.keyword import GoogleAdsUrlCustomParameter
from apps.api.integrations.google_ads.operations.url_custom_parameters import validate_url_custom_parameters
from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from .base import GoogleAdsStrictModel


def normalize_keyword_text(value: object) -> object:
    """Normalizes whitespace that Google Ads treats as equivalent."""
    return " ".join(value.split()) if isinstance(value, str) else value


def money_bid_to_micros(value: str, *, label: str = "Bid") -> int:
    candidate = value.strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", candidate) is None:
        raise ValueError(f"Enter the {label} as a positive decimal number.")
    if "." in candidate and len(candidate.rsplit(".", maxsplit=1)[1]) > 6:
        raise ValueError(f"The {label} can have at most six decimal places.")
    try:
        amount = Decimal(candidate)
    except InvalidOperation as exc:
        raise ValueError(f"Enter the {label} as a positive decimal number.") from exc
    micros = amount * Decimal(1_000_000)
    if amount <= 0:
        raise ValueError(f"The {label} must be greater than zero.")
    if int(micros) > GOOGLE_ADS_INT64_MAX:
        raise ValueError(f"The {label} is too large for Google Ads.")
    return int(micros)


def _valid_cpc_bid(value: str) -> str:
    money_bid_to_micros(value, label="CPC bid")
    return value.strip()


def cpc_bid_to_micros(value: str) -> int:
    return money_bid_to_micros(value, label="CPC bid")


GoogleAdsCpcBid = Annotated[
    str,
    Field(
        min_length=1,
        max_length=32,
        description=(
            "Optional cost-per-click bid in the Google Ads account currency, with up to "
            "six decimal places. Omit it to use the ad group's bid."
        ),
    ),
    AfterValidator(_valid_cpc_bid),
]


def _bounded_http_url(value: str) -> str:
    candidate = value.strip()
    if not re.fullmatch(r"https?://[^\s]+", candidate, flags=re.IGNORECASE):
        raise ValueError("Enter a complete HTTP or HTTPS URL.")
    return candidate


GoogleAdsFinalUrl = Annotated[
    str,
    Field(min_length=1, max_length=2048),
    AfterValidator(_bounded_http_url),
]


class GoogleAdsPositiveKeywordEntry(GoogleAdsStrictModel):
    text: str = Field(min_length=1, max_length=80)
    match_type: Literal["EXACT", "PHRASE", "BROAD"]
    status: Literal["ENABLED", "PAUSED"] = "ENABLED"
    cpc_bid: GoogleAdsCpcBid | None = None
    final_urls: Annotated[list[GoogleAdsFinalUrl], Field(max_length=10)] | None = None
    final_mobile_urls: Annotated[list[GoogleAdsFinalUrl], Field(max_length=10)] | None = None
    final_url_suffix: Annotated[str, Field(max_length=2048)] | None = None
    tracking_url_template: Annotated[str, Field(max_length=2048)] | None = None
    url_custom_parameters: dict[str, str] | None = None

    @field_validator("cpc_bid", mode="before")
    @classmethod
    def normalize_empty_cpc_bid(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("final_url_suffix", "tracking_url_template", mode="before")
    @classmethod
    def normalize_empty_optional_text(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("url_custom_parameters")
    @classmethod
    def validate_custom_parameters(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        return validate_url_custom_parameters(value)

    @model_validator(mode="after")
    def validate_tracking_template_dependency(self) -> GoogleAdsPositiveKeywordEntry:
        if self.tracking_url_template and not self.final_urls:
            raise ValueError("Add at least one final URL when using a tracking URL template.")
        return self

    @field_validator("text", mode="before")
    @classmethod
    def normalize_text_whitespace(cls, value: object) -> object:
        return normalize_keyword_text(value)

    @field_validator("text")
    @classmethod
    def validate_word_count(cls, value: str) -> str:
        if len(value.split()) > 10:
            raise ValueError("Google Ads keywords can contain at most 10 words")
        return value


class GoogleAdsPositiveKeywordOutcome(GoogleAdsStrictModel):
    campaign_id: str = Field(pattern=r"^\d+$")
    campaign_name: str
    ad_group_id: str = Field(pattern=r"^\d+$")
    ad_group_name: str
    requested: GoogleAdsPositiveKeywordRequested
    observed: GoogleAdsPositiveKeywordRequested | None = None
    observed_truncated: bool = False
    keyword: GoogleAdsKeywordReference | None = None
    previous_state: Literal["absent", "existing"]
    outcome: Literal["added", "skipped_existing", "failed", "unverified"]
    external_ref: str | None = None
    error_code: str | None = None
    message: str | None = None


class GoogleAdsPositiveKeywordRequested(GoogleAdsStrictModel):
    text: str
    match_type: Literal["EXACT", "PHRASE", "BROAD"]
    status: Literal["ENABLED", "PAUSED"]
    cpc_bid: str | None = None
    cpc_bid_micros: str | None = Field(default=None, pattern=r"^\d+$")
    final_urls: list[str] = Field(default_factory=list, max_length=10)
    final_mobile_urls: list[str] = Field(default_factory=list, max_length=10)
    final_url_suffix: str | None = None
    tracking_url_template: str | None = None
    url_custom_parameters: list[GoogleAdsUrlCustomParameter] = Field(
        default_factory=list, max_length=8
    )


class GoogleAdsPositiveKeywordCounts(GoogleAdsStrictModel):
    added: int = Field(ge=0)
    skipped_existing: int = Field(ge=0)
    failed: int = Field(ge=0)
    unverified: int = Field(ge=0)


class GoogleAdsPositiveKeywordSamples(GoogleAdsStrictModel):
    added: list[GoogleAdsPositiveKeywordOutcome]
    skipped_existing: list[GoogleAdsPositiveKeywordOutcome]
    failed: list[GoogleAdsPositiveKeywordOutcome]
    unverified: list[GoogleAdsPositiveKeywordOutcome]


class GoogleAdsCreatePositiveKeywordsData(GoogleAdsStrictModel):
    currency_code: str = Field(min_length=3, max_length=16)
    counts: GoogleAdsPositiveKeywordCounts
    samples: GoogleAdsPositiveKeywordSamples
    samples_truncated: bool
    audit_note: str | None = None


class GoogleAdsCreatePositiveKeywordsEntry(IntegrationFanOutEntry):
    data: GoogleAdsCreatePositiveKeywordsData | None = None


class GoogleAdsCreatePositiveKeywordsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsCreatePositiveKeywordsEntry]


class GoogleAdsPositiveKeywordStatusOutcome(GoogleAdsStrictModel):
    keyword: GoogleAdsKeywordReference
    previous_status: Literal["ENABLED", "PAUSED"]
    requested_status: Literal["ENABLED", "PAUSED"]
    outcome: Literal["updated", "already_set", "failed", "unverified"]
    external_ref: str | None = None
    error_code: str | None = None
    message: str | None = None


class GoogleAdsPositiveKeywordStatusCounts(GoogleAdsStrictModel):
    updated: int = Field(ge=0)
    already_set: int = Field(ge=0)
    failed: int = Field(ge=0)
    unverified: int = Field(ge=0)


class GoogleAdsPositiveKeywordStatusSamples(GoogleAdsStrictModel):
    updated: list[GoogleAdsPositiveKeywordStatusOutcome]
    already_set: list[GoogleAdsPositiveKeywordStatusOutcome]
    failed: list[GoogleAdsPositiveKeywordStatusOutcome]
    unverified: list[GoogleAdsPositiveKeywordStatusOutcome]


class GoogleAdsUpdatePositiveKeywordStatusData(GoogleAdsStrictModel):
    counts: GoogleAdsPositiveKeywordStatusCounts
    samples: GoogleAdsPositiveKeywordStatusSamples
    samples_truncated: bool
    audit_note: str | None = None


class GoogleAdsUpdatePositiveKeywordStatusEntry(IntegrationFanOutEntry):
    data: GoogleAdsUpdatePositiveKeywordStatusData | None = None


class GoogleAdsUpdatePositiveKeywordStatusOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsUpdatePositiveKeywordStatusEntry]
