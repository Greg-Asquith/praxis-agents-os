# apps/api/integrations/google_ads/tools/utils/positive_keyword_removal_results.py

"""Bounded Google Ads keyword removal results."""

from collections.abc import Mapping
from typing import Any, Literal

from integrations.google_ads.references import GoogleAdsKeywordReference

from .bounded_outcome_results import bounded_outcome_result, optional_text

type PositiveKeywordRemovalOutcome = Literal["removed", "failed", "unverified"]

MAX_POSITIVE_KEYWORD_REMOVAL_RESULT_CHARS = 12_000
MAX_POSITIVE_KEYWORD_REMOVAL_PUBLIC_RESULT_CHARS = 3_000_000
_MODEL_SAMPLES_PER_OUTCOME = 10
_AUDIT_NOTE = "Complete bounded removal evidence is retained in the audit trail."
_OUTCOMES: tuple[PositiveKeywordRemovalOutcome, ...] = ("removed", "failed", "unverified")


def bounded_positive_keyword_removal_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Returns exact counts and representative removal rows for model context."""
    return bounded_outcome_result(
        _samples(result),
        max_chars=MAX_POSITIVE_KEYWORD_REMOVAL_RESULT_CHARS,
        max_samples_per_outcome=_MODEL_SAMPLES_PER_OUTCOME,
        additional_fields={"audit_note": _AUDIT_NOTE},
    )


def display_positive_keyword_removal_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Returns every accepted removal row for the transcript."""
    samples = _samples(result)
    return {
        "counts": {outcome: len(rows) for outcome, rows in samples.items()},
        "samples": samples,
        "samples_truncated": False,
        "audit_note": None,
    }


def _samples(result: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    keywords = result.get("keywords")
    if not isinstance(keywords, list):
        raise TypeError("Keyword removal result is missing keyword rows")
    return {
        outcome: [_keyword_sample(row) for row in keywords if row.get("outcome") == outcome]
        for outcome in _OUTCOMES
    }


def _keyword_sample(row: Mapping[str, Any]) -> dict[str, Any]:
    reference = row.get("reference")
    if not isinstance(reference, GoogleAdsKeywordReference):
        reference = GoogleAdsKeywordReference.model_validate(reference)
    return {
        "reference": reference.model_dump(mode="json"),
        "previous_status": str(row.get("previous_status", ""))[:64],
        "resulting_status": optional_text(row.get("resulting_status"), 64),
        "outcome": row.get("outcome"),
        "external_ref": optional_text(row.get("external_ref"), 1_000),
        "error_code": optional_text(row.get("error_code"), 100),
        "message": optional_text(row.get("message"), 500),
    }
