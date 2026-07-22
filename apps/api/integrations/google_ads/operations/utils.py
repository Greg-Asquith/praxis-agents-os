# apps/api/integrations/google_ads/operations/utils.py

"""Shared response and safety helpers for Google Ads operations."""

import re
from typing import Any

from services.agents.runtime.untrusted import UntrustedContent

_LIMIT_PATTERN = re.compile(r"\bLIMIT\s+(\d+)\b", re.IGNORECASE)


def stream_rows(payload: Any) -> list[dict[str, Any]]:
    """Flatten the page envelopes returned by Google Ads searchStream."""
    pages = payload if isinstance(payload, list) else [payload]
    rows: list[dict[str, Any]] = []
    for page in pages:
        if not isinstance(page, dict) or not isinstance(page.get("results"), list):
            continue
        rows.extend(item for item in page["results"] if isinstance(item, dict))
    return rows


def bounded_query(query: str, *, max_rows: int) -> str:
    """Ask Google for at most one row beyond the model-visible cap."""
    request_limit = max_rows + 1
    normalized = query.strip().rstrip(";")
    match = _LIMIT_PATTERN.search(normalized)
    if match is None:
        return f"{normalized} LIMIT {request_limit}"
    if int(match.group(1)) <= request_limit:
        return normalized
    return _LIMIT_PATTERN.sub(f"LIMIT {request_limit}", normalized, count=1)

def operation_index(location: Any) -> int | None:
    if not isinstance(location, dict):
        return None
    for element in location.get("fieldPathElements", []):
        if isinstance(element, dict) and element.get("fieldName") == "operations":
            try:
                return int(element.get("index"))
            except (TypeError, ValueError):
                return None
    return None