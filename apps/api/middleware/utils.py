# apps/api/middleware/utils.py

"""Shared helpers for API middleware."""

import logging
from collections.abc import Mapping

from core.settings import settings

logger = logging.getLogger(__name__)

_BASE64_OVERHEAD_RATIO = 4 / 3
_BASE64_JSON_BUFFER_BYTES = 1024 * 1024  # 1MB buffer for JSON wrapper/headers
_REDACTED_LOG_VALUE = "[REDACTED]"
_REQUEST_LOG_HEADER_ALLOWLIST = frozenset(
    {
        "accept",
        "accept-encoding",
        "content-length",
        "content-type",
        "origin",
        "referer",
        "user-agent",
        "x-forwarded-for",
        "x-real-ip",
        "x-request-id",
        "x-workspace",
    }
)
_SENSITIVE_LOG_KEY_MARKERS = (
    "authorization",
    "cookie",
    "token",
    "secret",
    "password",
    "api-key",
    "apikey",
    "session",
    "credential",
    "signature",
)


def _is_app_frame_path(path: str) -> bool:
    """Return whether the request targets the authenticated App frame endpoint."""
    prefix = f"{settings.API_V1_PREFIX}/apps/"
    return path.startswith(prefix) and path.endswith("/frame")


def _base64_request_limit(raw_max_bytes: int) -> int:
    """Compute request body limit for base64 JSON payloads with small overhead buffer."""
    return int(raw_max_bytes * _BASE64_OVERHEAD_RATIO) + _BASE64_JSON_BUFFER_BYTES


def _normalize_log_key(key: str) -> str:
    """Normalize log keys for stable allowlist/redaction checks."""
    return key.strip().lower().replace("_", "-")


def _redact_sensitive_log_fields(fields: Mapping[str, str]) -> dict[str, str]:
    """Redact any sensitive keys from a mapping before structured logging."""
    redacted: dict[str, str] = {}
    for key, value in fields.items():
        normalized_key = _normalize_log_key(key)
        if any(marker in normalized_key for marker in _SENSITIVE_LOG_KEY_MARKERS):
            redacted[normalized_key] = _REDACTED_LOG_VALUE
        else:
            redacted[normalized_key] = value
    return redacted


def _sanitize_headers_for_logging(headers: Mapping[str, str]) -> dict[str, str]:
    """Default-deny request header logging with explicit allowlist + redaction."""
    allowlisted_headers: dict[str, str] = {}
    for key, value in headers.items():
        normalized_key = _normalize_log_key(key)
        if normalized_key in _REQUEST_LOG_HEADER_ALLOWLIST:
            allowlisted_headers[normalized_key] = value
    return _redact_sensitive_log_fields(allowlisted_headers)
