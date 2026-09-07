# apps/api/integrations/google_ads/tools/utils/positive_keyword_update_results.py

"""Bounded result shaping for positive-keyword updates."""

import json
from collections.abc import Mapping, Sequence
from typing import Any

from integrations.google_ads.references import GoogleAdsKeywordReference

from .bounded_outcome_results import bounded_outcome_result, optional_text

MAX_POSITIVE_KEYWORD_UPDATE_PUBLIC_RESULT_CHARS = 1_000_000
_MODEL_RESULT_CHARS = 12_000
_MODEL_SAMPLES_PER_OUTCOME = 10
_OUTCOMES = ("updated", "already_set", "failed", "unverified")
_AUDIT_NOTE = "Complete bounded keyword update evidence is retained in the audit trail."


def bounded_positive_keyword_update_result(
    rows: Sequence[Mapping[str, Any]], *, currency_code: str
) -> dict[str, Any]:
    """Returns exact counts and representative keyword rows for model context."""
    return _result(
        rows,
        max_chars=_MODEL_RESULT_CHARS,
        max_samples_per_outcome=_MODEL_SAMPLES_PER_OUTCOME,
        audit_note=_AUDIT_NOTE,
        currency_code=currency_code,
    )


def display_positive_keyword_update_result(
    rows: Sequence[Mapping[str, Any]], *, currency_code: str
) -> dict[str, Any]:
    """Returns every accepted keyword update row for the transcript."""
    samples = {
        outcome: [_row(row) for row in rows if row["outcome"] == outcome] for outcome in _OUTCOMES
    }
    return {
        "currency_code": currency_code,
        "audit_note": None,
        "counts": {outcome: len(values) for outcome, values in samples.items()},
        "samples": samples,
        "samples_truncated": False,
    }


def positive_keyword_update_result_upper_bound(
    variants: Sequence[Sequence[Mapping[str, Any]]], *, currency_code: str
) -> int:
    """Bounds mixed outcomes using the largest serialized value at each row position."""
    empty = display_positive_keyword_update_result([], currency_code=currency_code)
    empty["counts"] = dict.fromkeys(_OUTCOMES, 500)
    return _serialized_chars(empty) + sum(
        max(_serialized_chars(_row(row)) for row in alternatives) + 1
        for alternatives in zip(*variants, strict=True)
    )


def _serialized_chars(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def _result(
    rows: Sequence[Mapping[str, Any]],
    *,
    max_chars: int,
    max_samples_per_outcome: int | None,
    audit_note: str | None,
    currency_code: str,
) -> dict[str, Any]:
    outcomes = {
        outcome: [_row(value) for value in rows if value.get("outcome") == outcome]
        for outcome in _OUTCOMES
    }
    return bounded_outcome_result(
        outcomes,
        max_chars=max_chars,
        max_samples_per_outcome=max_samples_per_outcome,
        additional_fields={"currency_code": currency_code, "audit_note": audit_note},
    )


def _row(value: Mapping[str, Any]) -> dict[str, Any]:
    reference = value.get("keyword")
    if not isinstance(reference, GoogleAdsKeywordReference):
        reference = GoogleAdsKeywordReference.model_validate(reference)
    return {
        "keyword": reference.model_dump(mode="json"),
        "before": value.get("before"),
        "requested": value.get("requested"),
        "requested_fields": value.get("requested_fields"),
        "update_mask": value.get("update_mask"),
        "outcome": value.get("outcome"),
        "external_ref": optional_text(value.get("external_ref"), 1_000),
        "error_code": optional_text(value.get("error_code"), 100),
        "message": optional_text(value.get("message"), 500),
    }
