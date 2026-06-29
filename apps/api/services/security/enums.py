# apps/api/services/security/enums.py

"""Controlled vocabulary for security events.

This StrEnum keeps ``event_type`` values consistent across writers so the log
stays queryable. Members are plain strings, so they persist and compare exactly
like the literals they replace.
"""

from enum import StrEnum


class SecurityEventType(StrEnum):
    """The kind of security-relevant activity recorded."""

    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    CSRF_VALIDATION_FAILED = "csrf_validation_failed"
