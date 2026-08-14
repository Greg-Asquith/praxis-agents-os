# apps/api/integrations/google_ads/tools/schemas/negative_keywords.py

"""Result contracts for shared-set negative keyword mutations."""

from services.integrations.context.results import (
    IntegrationFanOutEntry,
    IntegrationFanOutOutput,
)

from .base import GoogleAdsStrictModel


class GoogleAdsKeywordSample(GoogleAdsStrictModel):
    text: str
    match_type: str
    resource_name: str | None = None
    scope: str | None = None
    message: str | None = None
    error_code: str | None = None


class GoogleAdsAddKeywordCounts(GoogleAdsStrictModel):
    added: int
    skipped_existing: int
    failed: int


class GoogleAdsRemoveKeywordCounts(GoogleAdsStrictModel):
    removed: int
    not_found: int
    failed: int


class GoogleAdsAddKeywordSamples(GoogleAdsStrictModel):
    added: list[GoogleAdsKeywordSample]
    skipped_existing: list[GoogleAdsKeywordSample]
    failed: list[GoogleAdsKeywordSample]


class GoogleAdsRemoveKeywordSamples(GoogleAdsStrictModel):
    removed: list[GoogleAdsKeywordSample]
    not_found: list[GoogleAdsKeywordSample]
    failed: list[GoogleAdsKeywordSample]


class GoogleAdsAddNegativeKeywordsData(GoogleAdsStrictModel):
    counts: GoogleAdsAddKeywordCounts
    samples: GoogleAdsAddKeywordSamples
    samples_truncated: bool
    audit_note: str | None = None


class GoogleAdsRemoveNegativeKeywordsData(GoogleAdsStrictModel):
    counts: GoogleAdsRemoveKeywordCounts
    samples: GoogleAdsRemoveKeywordSamples
    samples_truncated: bool
    audit_note: str | None = None


class GoogleAdsAddNegativeKeywordsEntry(IntegrationFanOutEntry):
    data: GoogleAdsAddNegativeKeywordsData | None = None


class GoogleAdsRemoveNegativeKeywordsEntry(IntegrationFanOutEntry):
    data: GoogleAdsRemoveNegativeKeywordsData | None = None


class GoogleAdsAddNegativeKeywordsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsAddNegativeKeywordsEntry]


class GoogleAdsRemoveNegativeKeywordsOutput(IntegrationFanOutOutput):
    results: list[GoogleAdsRemoveNegativeKeywordsEntry]
