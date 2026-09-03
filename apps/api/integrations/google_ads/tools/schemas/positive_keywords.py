# apps/api/integrations/google_ads/tools/schemas/positive_keywords.py

"""Input and result contracts for Google Ads positive-keyword actions."""

import re
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, field_validator

from integrations.google_ads.constants import GOOGLE_ADS_INT64_MAX
from integrations.google_ads.references import GoogleAdsKeywordReference
from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from .base import GoogleAdsStrictModel


def normalize_keyword_text(value: object) -> object:
    """Normalizes whitespace that Google Ads treats as equivalent."""
    return " ".join(value.split()) if isinstance(value, str) else value


def cpc_bid_to_micros(value: str) -> int:
    candidate = value.strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", candidate) is None:
        raise ValueError("Enter the CPC bid as a positive decimal number.")
    try:
        amount = Decimal(candidate)
    except InvalidOperation as exc:
        raise ValueError("Enter the CPC bid as a positive decimal number.") from exc
    micros = amount * Decimal(1_000_000)
    if amount <= 0:
        raise ValueError("The CPC bid must be greater than zero.")
    if micros != micros.to_integral_value():
        raise ValueError("The CPC bid can have at most six decimal places.")
    if int(micros) > GOOGLE_ADS_INT64_MAX:
        raise ValueError("The CPC bid is too large for Google Ads.")
    return int(micros)


def _valid_cpc_bid(value: str) -> str:
    cpc_bid_to_micros(value)
    return value.strip()


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


class GoogleAdsPositiveKeywordEntry(GoogleAdsStrictModel):
    text: str = Field(min_length=1, max_length=80)
    match_type: Literal["EXACT", "PHRASE", "BROAD"]
    cpc_bid: GoogleAdsCpcBid | None = None

    @field_validator("cpc_bid", mode="before")
    @classmethod
    def normalize_empty_cpc_bid(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

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
    keyword: GoogleAdsKeywordReference | None = None
    text: str
    match_type: Literal["EXACT", "PHRASE", "BROAD"]
    cpc_bid: str | None = None
    cpc_bid_micros: str | None = Field(default=None, pattern=r"^\d+$")
    previous_state: Literal["absent", "existing"]
    outcome: Literal["added", "skipped_existing", "failed", "unverified"]
    external_ref: str | None = None
    error_code: str | None = None
    message: str | None = None


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


class GoogleAdsAddPositiveKeywordsData(GoogleAdsStrictModel):
    currency_code: str = Field(min_length=3, max_length=16)
    counts: GoogleAdsPositiveKeywordCounts
    samples: GoogleAdsPositiveKeywordSamples
    samples_truncated: bool
    audit_note: str | None = None


class GoogleAdsAddPositiveKeywordsEntry(IntegrationFanOutEntry):
    data: GoogleAdsAddPositiveKeywordsData | None = None


class GoogleAdsAddPositiveKeywordsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsAddPositiveKeywordsEntry]


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
