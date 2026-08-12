# apps/api/integrations/google_ads/operations/utils.py

"""Shared response and safety helpers for Google Ads operations."""

import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

_LIMIT_PATTERN = re.compile(r"\bLIMIT\s+(\d+)\b", re.IGNORECASE)
_GAQL_LIKE_LITERAL_ESCAPES = {
    "\\": "\\\\",
    "'": "\\'",
    "[": "[[]",
    "]": "[]]",
    "%": "[%]",
    "_": "[_]",
}


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


def escape_gaql_like_literal(value: str, *, max_length: int = 200) -> str:
    """Escape a bounded user value before interpolation into a GAQL LIKE literal."""
    escaped: list[str] = []
    escaped_length = 0
    for character in value:
        encoded = _GAQL_LIKE_LITERAL_ESCAPES.get(character, character)
        if escaped_length + len(encoded) > max_length:
            break
        escaped.append(encoded)
        escaped_length += len(encoded)
    return "".join(escaped)


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


def grouped_partial_failure_errors[OperationValue](
    payload: Any,
    operation_values: Sequence[OperationValue],
    *,
    value_to_error_fields: Callable[[OperationValue], Mapping[str, str]],
    unattributed_error_fields: Mapping[str, str],
    default_message: str,
) -> tuple[dict[int, dict[str, str]], list[dict[str, str]]]:
    """Group Google Ads diagnostics by operation index.

    Google may emit several diagnostics for one rejected operation. Keeping one
    result per operation makes downstream counts describe failed mutations rather
    than diagnostic rows.
    """
    if not isinstance(payload, dict):
        return {}, []
    partial = payload.get("partialFailureError")
    if not isinstance(partial, dict):
        return {}, []
    indexed_diagnostics: dict[int, list[tuple[str, str]]] = {}
    unattributed_diagnostics: list[tuple[str, str]] = []
    for detail in partial.get("details", []):
        if not isinstance(detail, dict):
            continue
        for item in detail.get("errors", []):
            if not isinstance(item, dict):
                continue
            index = operation_index(item.get("location", {}))
            diagnostic = (
                str(item.get("message", default_message)),
                _error_code(item.get("errorCode")),
            )
            if index is not None and 0 <= index < len(operation_values):
                indexed_diagnostics.setdefault(index, []).append(diagnostic)
            else:
                unattributed_diagnostics.append(diagnostic)
    if not indexed_diagnostics and not unattributed_diagnostics and partial.get("message"):
        unattributed_diagnostics.append((str(partial["message"]), _error_code(partial.get("code"))))
    indexed = {
        index: {
            **value_to_error_fields(operation_values[index]),
            **_combined_diagnostics(diagnostics),
        }
        for index, diagnostics in indexed_diagnostics.items()
    }
    unattributed = (
        [{**unattributed_error_fields, **_combined_diagnostics(unattributed_diagnostics)}]
        if unattributed_diagnostics
        else []
    )
    return indexed, unattributed


def _combined_diagnostics(diagnostics: Sequence[tuple[str, str]]) -> dict[str, str]:
    messages = list(dict.fromkeys(message for message, _code in diagnostics))
    codes = list(dict.fromkeys(code for _message, code in diagnostics))
    return {
        "message": " | ".join(messages),
        "error_code": " | ".join(codes),
    }


def _error_code(value: Any) -> str:
    if isinstance(value, dict):
        for code in value.values():
            if isinstance(code, str) and code:
                return code
        return "unknown"
    if value is None:
        return "unknown"
    return str(value)
