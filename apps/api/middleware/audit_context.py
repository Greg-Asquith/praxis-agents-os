# apps/api/middleware/audit_context.py

"""Audit context middleware for the FastAPI application."""

import logging
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from core.rate_limiting import get_client_ip

logger = logging.getLogger(__name__)


class AuditContextMiddleware(BaseHTTPMiddleware):
    """Capture request context for audit logging.

    Sets request.state.audit_context with:
    - request_id: Correlation ID (from X-Request-ID or generated)
    - ip_address: Client IP address (handles proxy headers via get_client_ip)
    - user_agent: User-Agent header

    This context is used by the audit service to automatically populate
    request metadata in audit logs.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # RequestIDMiddleware runs before AuditContext on the request path
        # so request.scope["request_id"] is reliably set; fall back to the
        # incoming header only as a safety net (e.g. in test harnesses).
        request_id = request.scope.get("request_id") or request.headers.get("x-request-id")

        # Extract client IP using helper that handles proxy headers
        ip_address = get_client_ip(request)

        # Extract user agent
        user_agent = request.headers.get("user-agent")

        # Store in request state for audit service
        request.state.audit_context = {
            "request_id": request_id,
            "ip_address": ip_address,
            "user_agent": user_agent,
        }

        return await call_next(request)
