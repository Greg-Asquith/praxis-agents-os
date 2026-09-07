# apps/api/integrations/google_ads/tools/utils/bounded_outcome_results.py

"""Shared size-bounded sampling for mutation outcome results."""

import json
from collections.abc import Mapping, Sequence
from typing import Any


def bounded_outcome_result(
    outcomes: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    max_chars: int,
    max_samples_per_outcome: int | None,
    additional_fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return exact counts and round-robin samples within a serialized-size limit."""
    response: dict[str, Any] = {
        **(additional_fields or {}),
        "counts": {key: len(values) for key, values in outcomes.items()},
        "samples": {key: [] for key in outcomes},
        "samples_truncated": True,
    }
    max_rows = max((len(values) for values in outcomes.values()), default=0)
    if max_samples_per_outcome is not None:
        max_rows = min(max_rows, max_samples_per_outcome)
    for index in range(max_rows):
        for key, values in outcomes.items():
            if index >= len(values):
                continue
            samples = response["samples"][key]
            candidate = {
                **response,
                "samples": {**response["samples"], key: [*samples, values[index]]},
            }
            if _serialized_chars(candidate) <= max_chars:
                samples.append(values[index])
    response["samples_truncated"] = any(
        len(response["samples"][key]) < len(values) for key, values in outcomes.items()
    )
    return response


def optional_text(value: Any, max_chars: int) -> str | None:
    """Return optional result text within its field-specific bound."""
    return str(value)[:max_chars] if value is not None else None


def _serialized_chars(value: object) -> int:
    return len(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
