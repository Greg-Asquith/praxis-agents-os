# apps/api/services/audit_events/utils.py

"""Helpers specific to audit event recording."""

from typing import Any

from fastapi import Request

from core.rate_limiting import get_client_ip


def request_audit_context(request: Request | None) -> dict[str, str | None]:
    """Return stable request metadata for audit rows or deferred run metadata."""
    if request is None:
        return {"request_id": None, "ip_address": None, "user_agent": None}

    audit_context = getattr(request.state, "audit_context", None)
    if isinstance(audit_context, dict):
        return {
            "request_id": _string_or_none(audit_context.get("request_id")),
            "ip_address": _string_or_none(audit_context.get("ip_address")),
            "user_agent": _string_or_none(audit_context.get("user_agent")),
        }

    return {
        "request_id": _string_or_none(
            request.scope.get("request_id") or request.headers.get("x-request-id")
        ),
        "ip_address": get_client_ip(request),
        "user_agent": request.headers.get("user-agent"),
    }


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
