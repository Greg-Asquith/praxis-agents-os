# apps/api/integrations/google_ads/operations/utils.py

"""Shared response and safety helpers for Google Ads operations."""

import re
from typing import Any

_LIMIT_PATTERN = re.compile(r"\bLIMIT\s+(\d+)\b", re.IGNORECASE)


def stream_rows(payload: Any, *, max_rows: int | None = None) -> list[dict[str, Any]]:
    """Flatten Google Ads searchStream pages without collecting beyond a row budget."""
    if max_rows is not None and max_rows <= 0:
        return []
    pages = payload if isinstance(payload, list) else [payload]
    rows: list[dict[str, Any]] = []
    for page in pages:
        if not isinstance(page, dict) or not isinstance(page.get("results"), list):
            continue
        for item in page["results"]:
            if isinstance(item, dict):
                rows.append(item)
                if max_rows is not None and len(rows) >= max_rows:
                    return rows
    return rows


def bounded_query(query: str, *, max_rows: int) -> str:
    """Ask Google for at most one row beyond the model-visible cap."""
    request_limit = max_rows + 1
    normalized = _without_comments(query).strip().rstrip(";").rstrip()
    masked = _mask_quoted_values(normalized)
    matches = list(_LIMIT_PATTERN.finditer(masked))
    terminal_match = matches[-1] if matches and not masked[matches[-1].end() :].strip() else None
    effective_limit = (
        min(int(terminal_match.group(1)), request_limit)
        if terminal_match is not None
        else request_limit
    )

    # Remove every clause-like LIMIT outside quoted values. This turns a misplaced
    # LIMIT into a single provider-enforced terminal clause instead of trusting the
    # first LIMIT-looking token in model-authored text.
    for match in reversed(matches):
        normalized = normalized[: match.start()].rstrip() + " " + normalized[match.end() :].lstrip()
    return f"{normalized.rstrip()} LIMIT {effective_limit}"


def _without_comments(query: str) -> str:
    """Remove SQL-style comments while preserving quoted GAQL values."""
    output: list[str] = []
    index = 0
    quote: str | None = None
    while index < len(query):
        character = query[index]
        following = query[index + 1] if index + 1 < len(query) else ""
        if quote is not None:
            output.append(character)
            if character == "\\" and following:
                output.append(following)
                index += 2
                continue
            if character == quote:
                quote = None
            index += 1
            continue
        if character in {"'", '"'}:
            quote = character
            output.append(character)
            index += 1
            continue
        if (character == "-" and following == "-") or character == "#":
            newline = query.find("\n", index)
            if newline == -1:
                break
            output.append("\n")
            index = newline + 1
            continue
        if character == "/" and following == "*":
            comment_end = query.find("*/", index + 2)
            if comment_end == -1:
                break
            output.append(" ")
            index = comment_end + 2
            continue
        output.append(character)
        index += 1
    return "".join(output)


def _mask_quoted_values(query: str) -> str:
    """Mask quoted values so clause matching only examines GAQL syntax."""
    masked = list(query)
    index = 0
    quote: str | None = None
    while index < len(query):
        character = query[index]
        if quote is None:
            if character in {"'", '"'}:
                quote = character
                masked[index] = " "
        else:
            masked[index] = " "
            if character == "\\" and index + 1 < len(query):
                masked[index + 1] = " "
                index += 1
            elif character == quote:
                quote = None
        index += 1
    return "".join(masked)


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
