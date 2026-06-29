# apps/api/utils/json_safe.py

"""Shared JSON-safe serialisation helpers with sensitive-key redaction.

Both security events and audit events use this module so that the redacting
logic lives in exactly one place.  The canonical implementation is the
*redacting* variant from audit_events: if a top-level or nested dict key
matches a sensitive marker (token, password, secret, …) the value is
replaced with ``[REDACTED]``.
"""

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any
from uuid import UUID

SENSITIVE_DETAIL_KEY_MARKERS = (
    "authorization",
    "cookie",
    "csrf",
    "password",
    "secret",
    "signature",
    "token",
)
REDACTED_VALUE = "[REDACTED]"


def json_safe_details(details: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively coerce a details mapping to a JSON-serialisable dict.

    Sensitive keys are replaced with ``REDACTED_VALUE`` at every level of
    nesting.
    """
    return {str(key): json_safe_value(value, key=str(key)) for key, value in details.items()}


def json_safe_value(value: Any, *, key: str | None = None) -> Any:
    """Coerce *value* to a JSON-safe type, redacting sensitive keys."""
    if key is not None and _is_sensitive_key(key):
        return REDACTED_VALUE
    if isinstance(value, Mapping):
        return {
            str(item_key): json_safe_value(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [json_safe_value(item_value) for item_value in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    # Fallback: stringify anything not natively JSON-serialisable
    # (e.g. Decimal, set, custom objects) so audit/security writes never fail.
    return str(value)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_").replace(" ", "_")
    return any(marker in normalized for marker in SENSITIVE_DETAIL_KEY_MARKERS)
