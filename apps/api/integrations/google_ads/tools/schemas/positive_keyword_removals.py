# apps/api/integrations/google_ads/tools/schemas/positive_keyword_removals.py

"""Fixed positive-keyword removal result contracts."""

from typing import Literal

from pydantic import Field

from integrations.google_ads.references import GoogleAdsKeywordReference
from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from .base import GoogleAdsStrictModel


class GoogleAdsPositiveKeywordRemovalOutcome(GoogleAdsStrictModel):
    reference: GoogleAdsKeywordReference
    previous_status: str
    resulting_status: str | None = None
    outcome: Literal["removed", "failed", "unverified"]
    external_ref: str | None = None
    error_code: str | None = None
    message: str | None = None


class GoogleAdsPositiveKeywordRemovalCounts(GoogleAdsStrictModel):
    removed: int = Field(ge=0)
    failed: int = Field(ge=0)
    unverified: int = Field(ge=0)


class GoogleAdsPositiveKeywordRemovalSamples(GoogleAdsStrictModel):
    removed: list[GoogleAdsPositiveKeywordRemovalOutcome]
    failed: list[GoogleAdsPositiveKeywordRemovalOutcome]
    unverified: list[GoogleAdsPositiveKeywordRemovalOutcome]


class GoogleAdsRemovePositiveKeywordsData(GoogleAdsStrictModel):
    counts: GoogleAdsPositiveKeywordRemovalCounts
    samples: GoogleAdsPositiveKeywordRemovalSamples
    samples_truncated: bool
    audit_note: str | None = None


class GoogleAdsRemovePositiveKeywordsEntry(IntegrationFanOutEntry):
    data: GoogleAdsRemovePositiveKeywordsData | None = None


class GoogleAdsRemovePositiveKeywordsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsRemovePositiveKeywordsEntry]
