# apps/api/middleware/rate_limit.py

"""Rate limiting middleware with durable auth budgets and in-memory general budgets."""

import json
import logging
from collections.abc import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from core.database import get_async_db_session_factory
from core.rate_limiting import (
    RateLimitResult,
    get_client_ip,
    get_login_failure_status,
    normalize_endpoint,
    rate_limit_response_details,
    rate_limiter,
)
from core.request_paths import redact_capability_path
from services.security import (
    SecurityEventType,
    safe_record_security_event,
    safe_record_security_event_committed,
)
from utils.validation import normalize_email

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware.

    Auth endpoints use stricter PostgreSQL-backed limits that fail closed. All
    other requests use per-minute and per-hour budgets counted in memory.
    """

    def __init__(self, app, exclude_paths: list[str] | None = None):
        super().__init__(app)
        self.exclude_paths = exclude_paths or [
            "/healthz",
            "/readyz",
            "/api/metrics",
        ]
        self.durable_limit_types = {
            "login_attempts",
            "registration",
            "password_reset",
        }

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Apply rate limiting to incoming requests."""

        # Browsers may issue CORS preflight probes before the real request.
        # Those are transport-level checks and should not consume auth budgets.
        if request.method in ("OPTIONS", "HEAD"):
            return await call_next(request)

        # Skip rate limiting for excluded paths
        if any(request.url.path.startswith(path) for path in self.exclude_paths):
            return await call_next(request)

        # Get client IP
        client_ip = get_client_ip(request)
        endpoint = redact_capability_path(request.url.path)
        rate_limit_endpoint = normalize_endpoint(endpoint)
        method = request.method

        # Determine rate limit type based on endpoint
        limit_type = self._get_limit_type(endpoint, method)
        login_email = await self._login_email(request, endpoint, limit_type)

        result = None
        if limit_type in self.durable_limit_types:
            try:
                result, blocked_resp = await self._check_durable_limit(
                    request, client_ip, endpoint, rate_limit_endpoint, limit_type, login_email
                )
            except Exception as e:
                # Fail closed on auth paths to prevent brute force during backend instability.
                logger.error(
                    f"RateLimitMiddleware fail-closed on {limit_type} due to error: {e}",
                    extra={"client_ip": client_ip, "endpoint": endpoint},
                    exc_info=True,
                )
                return JSONResponse(
                    status_code=503,
                    content={
                        "detail": "Service temporarily unavailable. Please try again shortly."
                    },
                )
            if blocked_resp is not None:
                return blocked_resp

        # General budgets stay in memory so ordinary requests don't need a connection.
        memory_limit_types = (
            ("requests_per_minute", "requests_per_hour")
            if limit_type == "requests_per_minute"
            else ("requests_per_hour",)
        )
        for memory_limit_type in memory_limit_types:
            memory_result = rate_limiter.check_memory_rate_limit(
                client_ip, rate_limit_endpoint, memory_limit_type
            )
            if not memory_result.allowed:
                await safe_record_security_event_committed(
                    **self._security_event(
                        request, client_ip, endpoint, memory_limit_type, memory_result
                    )
                )
                return self._rate_limited_response(endpoint, memory_limit_type, memory_result)
            result = result or memory_result

        response = await call_next(request)
        self._attach_rate_limit_headers(response, result)
        return response

    async def _check_durable_limit(
        self,
        request: Request,
        client_ip: str,
        endpoint: str,
        rate_limit_endpoint: str,
        limit_type: str,
        login_email: str | None,
    ) -> tuple[RateLimitResult | None, Response | None]:
        """Check an auth budget in its own committed session."""
        # The request session rolls back on 4xx responses, which would undo the
        # attempt count and the RATE_LIMIT_EXCEEDED event, so commit separately.
        session_factory = get_async_db_session_factory()
        async with session_factory() as db:
            try:
                if limit_type != "login_attempts":
                    result = await rate_limiter.check_rate_limit(
                        ip=client_ip,
                        endpoint=rate_limit_endpoint,
                        limit_type=limit_type,
                        db=db,
                    )
                elif login_email is not None:
                    result = await get_login_failure_status(client_ip, login_email, db)
                else:
                    return None, None
                blocked_resp = None
                if not result.allowed:
                    await safe_record_security_event(
                        db, **self._security_event(request, client_ip, endpoint, limit_type, result)
                    )
                    blocked_resp = self._rate_limited_response(endpoint, limit_type, result)
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        return result, blocked_resp

    @staticmethod
    def _security_event(
        request: Request,
        client_ip: str,
        endpoint: str,
        limit_type: str,
        result: RateLimitResult,
    ) -> dict:
        return {
            "event_type": SecurityEventType.RATE_LIMIT_EXCEEDED,
            "ip_address": client_ip,
            "user_agent": request.headers.get("user-agent", None),
            "user_email": None,
            "endpoint": endpoint,
            "details": {
                "limit_type": limit_type,
                "attempts": result.attempts,
                "limit": result.limit,
                "retry_after": result.retry_after,
            },
        }

    @staticmethod
    async def _login_email(
        request: Request,
        endpoint: str,
        limit_type: str,
    ) -> str | None:
        """Read the account key when the login request carries one."""
        if limit_type != "login_attempts" or not endpoint.lower().rstrip("/").endswith(
            "/auth/login"
        ):
            return None
        try:
            payload = json.loads(await request.body())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        email = payload.get("email") if isinstance(payload, dict) else None
        return normalize_email(email) if isinstance(email, str) else None

    def _rate_limited_response(self, endpoint: str, limit_type: str, result) -> Response:
        body = {
            "detail": f"Rate limit exceeded. Try again in {result.retry_after} seconds.",
            "rate_limit": rate_limit_response_details(result, limit_type=limit_type),
        }
        response = JSONResponse(status_code=429, content=body)

        self._attach_rate_limit_headers(response, result)
        if result.retry_after is not None:
            response.headers["Retry-After"] = str(result.retry_after)
        return response

    @staticmethod
    def _attach_rate_limit_headers(response: Response, result) -> None:
        # No limit (rate limiting disabled) → nothing meaningful to advertise.
        if result.limit is None:
            return
        response.headers.setdefault("X-RateLimit-Limit", str(result.limit))
        response.headers.setdefault(
            "X-RateLimit-Remaining",
            str(max(0, result.limit - result.attempts)),
        )
        response.headers.setdefault(
            "X-RateLimit-Reset",
            str(int(result.reset_time.timestamp())),
        )

    def _get_limit_type(self, endpoint: str, method: str) -> str:
        """Determine rate limit type based on endpoint and method."""

        # Authentication endpoints - stricter limits
        ep = endpoint.lower()
        if ep.rstrip("/").endswith("/auth/totp/verify"):
            return "login_attempts"
        if ep.rstrip("/").endswith("/auth/login"):
            return "login_attempts"
        if (
            ep.startswith("/api/v1/auth/oauth/")
            and ep.rstrip("/").endswith("/callback")
            and "/link/" not in ep
        ):
            return "login_attempts"
        if ("/auth/" in ep and ep.rstrip("/").endswith("/register")) or (
            "/api/v1/users" in ep and method == "POST"
        ):
            return "registration"
        if "/auth/" in ep and "/password/reset" in ep:
            return "password_reset"

        # All other traffic (API and non-API alike) gets the standard
        # per-minute budget. This is the deliberate catch-all default.
        return "requests_per_minute"
