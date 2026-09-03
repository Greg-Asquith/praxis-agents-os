# apps/api/integrations/google_ads/tools/utils/positive_keyword_status_results.py

"""Bounded result shaping for positive-keyword status updates."""

from collections.abc import Mapping, Sequence
from typing import Any

from integrations.google_ads.references import GoogleAdsKeywordReference

from .bounded_outcome_results import bounded_outcome_result, optional_text

MAX_POSITIVE_KEYWORD_STATUS_PUBLIC_RESULT_CHARS = 1_000_000
_MODEL_RESULT_CHARS = 12_000
_DISPLAY_RESULT_CHARS = 500_000
_MODEL_SAMPLES_PER_OUTCOME = 10
_OUTCOMES = ("updated", "already_set", "failed", "unverified")
_AUDIT_NOTE = "Complete bounded keyword status evidence is retained in the audit trail."


def bounded_positive_keyword_status_result(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Return exact counts and representative keyword rows for model context."""
    return _result(
        rows,
        max_chars=_MODEL_RESULT_CHARS,
        max_samples_per_outcome=_MODEL_SAMPLES_PER_OUTCOME,
        audit_note=_AUDIT_NOTE,
    )


def display_positive_keyword_status_result(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Return as many keyword status rows as fit the display budget."""
    return _result(
        rows,
        max_chars=_DISPLAY_RESULT_CHARS,
        max_samples_per_outcome=None,
        audit_note=None,
    )


def _result(
    rows: Sequence[Mapping[str, Any]],
    *,
    max_chars: int,
    max_samples_per_outcome: int | None,
    audit_note: str | None,
) -> dict[str, Any]:
    outcomes = {
        outcome: [_row(value) for value in rows if value.get("outcome") == outcome]
        for outcome in _OUTCOMES
    }
    return bounded_outcome_result(
        outcomes,
        max_chars=max_chars,
        max_samples_per_outcome=max_samples_per_outcome,
        additional_fields={"audit_note": audit_note},
    )


def _row(value: Mapping[str, Any]) -> dict[str, Any]:
    reference = value.get("keyword")
    if not isinstance(reference, GoogleAdsKeywordReference):
        reference = GoogleAdsKeywordReference.model_validate(reference)
    return {
        "keyword": reference.model_dump(mode="json"),
        "previous_status": value.get("previous_status"),
        "requested_status": value.get("requested_status"),
        "outcome": value.get("outcome"),
        "external_ref": optional_text(value.get("external_ref"), 1_000),
        "error_code": optional_text(value.get("error_code"), 100),
        "message": optional_text(value.get("message"), 500),
    }
