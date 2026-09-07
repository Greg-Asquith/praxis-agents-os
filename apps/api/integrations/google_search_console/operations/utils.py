# apps/api/integrations/google_search_console/operations/utils.py

"""Shared bounded response helpers for Google Search Console operations."""

import math
from typing import Any

from core.exceptions.integration import IntegrationValidationError
from services.agents.runtime.untrusted import UntrustedNode

MAX_PROVIDER_TEXT_LENGTH = 4_096
MAX_PROVIDER_STATUS_LENGTH = 128


def untrusted(value: Any, *, source_kind: str, source_ref: str) -> UntrustedNode:
    """Returns a bounded untrusted-content node for a provider value."""
    return UntrustedNode(
        source_kind=source_kind,
        source_ref=source_ref,
        content=bounded_text(value, max_length=MAX_PROVIDER_TEXT_LENGTH),
    )


def bounded_text(value: Any, *, max_length: int = MAX_PROVIDER_STATUS_LENGTH) -> str:
    """Returns a provider string capped to the requested length."""
    return str(value)[:max_length] if isinstance(value, str) else ""


def nonnegative_int(value: Any, *, operation: str) -> int:
    """Returns a nonnegative provider integer or rejects the response."""
    if isinstance(value, bool):
        raise invalid_response(operation)
    if isinstance(value, int):
        result = value
    elif (isinstance(value, float) and value.is_integer()) or (
        isinstance(value, str) and value.isascii() and value.isdigit()
    ):
        result = int(value)
    else:
        raise invalid_response(operation)
    if result < 0:
        raise invalid_response(operation)
    return result


def provider_bool(value: Any, *, operation: str) -> bool:
    """Returns a provider boolean or rejects the response."""
    if not isinstance(value, bool):
        raise invalid_response(operation)
    return value


def finite_float(value: Any, *, operation: str) -> float:
    """Returns a finite provider number or rejects the response."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid_response(operation)
    result = float(value)
    if not math.isfinite(result):
        raise invalid_response(operation)
    return result


def invalid_response(operation: str) -> IntegrationValidationError:
    """Returns the standard malformed-response error for an operation."""
    return IntegrationValidationError(
        "Google Search Console returned an invalid response",
        provider_key="google_search_console",
        operation=operation,
    )
