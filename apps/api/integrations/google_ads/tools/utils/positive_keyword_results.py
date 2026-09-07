# apps/api/integrations/google_ads/tools/utils/positive_keyword_results.py

"""Bounded result shaping for positive keyword mutations."""

from collections.abc import Mapping, Sequence
from typing import Any

from .bounded_outcome_results import bounded_outcome_result

MAX_POSITIVE_KEYWORD_RESULT_CHARS = 12_000
MAX_POSITIVE_KEYWORD_DISPLAY_CHARS = 2_400_000
MAX_POSITIVE_KEYWORD_PUBLIC_RESULT_CHARS = 2_500_000
_MODEL_SAMPLES_PER_OUTCOME = 10
_OUTCOMES = ("added", "skipped_existing", "failed", "unverified")
_AUDIT_NOTE = "Complete bounded keyword outcomes are retained in the audit trail."


def bounded_positive_keyword_result(
    rows: Sequence[Mapping[str, Any]], *, currency_code: str
) -> dict[str, Any]:
    """Returns exact counts and representative keyword rows for model context."""
    return _result(
        rows,
        max_chars=MAX_POSITIVE_KEYWORD_RESULT_CHARS,
        max_samples_per_outcome=_MODEL_SAMPLES_PER_OUTCOME,
        additional_fields={"audit_note": _AUDIT_NOTE, "currency_code": currency_code},
    )


def display_positive_keyword_result(
    rows: Sequence[Mapping[str, Any]], *, currency_code: str
) -> dict[str, Any]:
    """Returns every compact keyword outcome for application display."""
    outcomes = {
        outcome: [_display_row(row) for row in rows if row.get("outcome") == outcome]
        for outcome in _OUTCOMES
    }
    return {
        "currency_code": currency_code,
        "counts": {key: len(values) for key, values in outcomes.items()},
        "samples": outcomes,
        "samples_truncated": False,
    }


def _result(
    rows: Sequence[Mapping[str, Any]],
    *,
    max_chars: int,
    max_samples_per_outcome: int | None,
    additional_fields: Mapping[str, Any],
) -> dict[str, Any]:
    outcomes = {
        outcome: [dict(row) for row in rows if row.get("outcome") == outcome]
        for outcome in _OUTCOMES
    }
    return bounded_outcome_result(
        outcomes,
        max_chars=max_chars,
        max_samples_per_outcome=max_samples_per_outcome,
        additional_fields=additional_fields,
    )


def _display_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key != "keyword" and value is not None}
