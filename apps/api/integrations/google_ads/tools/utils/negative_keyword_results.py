# apps/api/integrations/google_ads/tools/utils/negative_keyword_results.py

"""Bounded model-visible negative-keyword mutation results."""

import json
from typing import Any

MAX_NEGATIVE_KEYWORD_RESULT_CHARS = 12_000
MAX_NEGATIVE_KEYWORD_PUBLIC_RESULT_CHARS = 1_000_000
MAX_NEGATIVE_KEYWORD_SAMPLES_PER_OUTCOME = 10

_AUDIT_NOTE = "Full applied-change details are retained in the audit trail."


def bounded_negative_keyword_result(result: dict[str, Any]) -> dict[str, Any]:
    """Return exact outcome counts and representative rows within a fixed budget."""
    return _bounded_result(_add_outcomes(result))


def complete_negative_keyword_result(result: dict[str, Any]) -> dict[str, Any]:
    """Return every add outcome for transcript display outside model context."""
    return _complete_result(_add_outcomes(result))


def bounded_negative_keyword_removal_result(result: dict[str, Any]) -> dict[str, Any]:
    """Return exact removal counts and representative rows within a fixed budget."""
    return _bounded_result(_removal_outcomes(result))


def complete_negative_keyword_removal_result(result: dict[str, Any]) -> dict[str, Any]:
    """Return every removal outcome for transcript display outside model context."""
    return _complete_result(_removal_outcomes(result))


def _add_outcomes(result: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    return {
        "added": [_keyword_sample(item, include_resource_name=True) for item in result["added"]],
        "skipped_existing": [_keyword_sample(item) for item in result["skipped_existing"]],
        "failed": [_error_sample(error) for error in result["keyword_errors"]],
    }


def _removal_outcomes(result: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    return {
        "removed": [
            _keyword_sample(item, include_resource_name=True) for item in result["removed"]
        ],
        "not_found": [_keyword_sample(item) for item in result["not_found"]],
        "failed": [_error_sample(error) for error in result["keyword_errors"]],
    }


def _bounded_result(outcomes: dict[str, list[dict[str, str]]]) -> dict[str, Any]:
    response: dict[str, Any] = {
        "counts": {key: len(values) for key, values in outcomes.items()},
        "samples": {key: [] for key in outcomes},
        "samples_truncated": True,
        "audit_note": _AUDIT_NOTE,
    }

    for index in range(MAX_NEGATIVE_KEYWORD_SAMPLES_PER_OUTCOME):
        for key, values in outcomes.items():
            if index >= len(values):
                continue
            samples = response["samples"][key]
            candidate = {
                **response,
                "samples": {**response["samples"], key: [*samples, values[index]]},
            }
            if _serialized_chars(candidate) <= MAX_NEGATIVE_KEYWORD_RESULT_CHARS:
                samples.append(values[index])

    response["samples_truncated"] = any(
        len(response["samples"][key]) < len(values) for key, values in outcomes.items()
    )
    return response


def _complete_result(outcomes: dict[str, list[dict[str, str]]]) -> dict[str, Any]:
    return {
        "counts": {key: len(values) for key, values in outcomes.items()},
        "samples": outcomes,
        "samples_truncated": False,
    }


def _keyword_sample(
    keyword: dict[str, Any],
    *,
    include_resource_name: bool = False,
) -> dict[str, str]:
    sample = {
        "text": str(keyword.get("text", ""))[:80],
        "match_type": str(keyword.get("match_type", ""))[:20],
    }
    if include_resource_name:
        sample["resource_name"] = str(keyword.get("resource_name", ""))[:1_000]
    return sample


def _error_sample(error: dict[str, Any]) -> dict[str, str]:
    sample = {
        "scope": str(error.get("scope", "account"))[:20],
        "message": str(error.get("message", ""))[:500],
        "error_code": str(error.get("error_code", "unknown"))[:100],
    }
    if sample["scope"] == "keyword":
        sample["text"] = str(error.get("text", ""))[:80]
        sample["match_type"] = str(error.get("match_type", ""))[:20]
    return sample


def _serialized_chars(value: object) -> int:
    return len(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )
    )
