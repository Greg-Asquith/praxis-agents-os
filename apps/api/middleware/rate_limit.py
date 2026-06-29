# apps/api/middleware/rate_limit.py

"""Rate limiting middleware using the PostgreSQL-backed limiter."""

import logging
from collections.abc import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from core.database import get_async_db_session_factory
from core.rate_limiting import get_client_ip, rate_limiter
from core.settings import settings
from services.security import SecurityEventType, safe_record_security_event

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Rate limiting middleware using PostgreSQL backend.

    Applies different rate limits based on endpoint patterns:
    - Auth endpoints: stricter limits
    - General API: standard limits
    - Static/health endpoints: relaxed limits
    """

    def __init__(self, app, exclude_paths: list[str] | None = None):
        super().__init__(app)
        self.exclude_paths = exclude_paths or [
            "/api/health",
            "/api/metrics",
        ]
        self.fail_closed_limit_types = {
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
        endpoint = request.url.path
        method = request.method

        # Determine rate limit type based on endpoint
        limit_type = self._get_limit_type(endpoint, method)

        async def _check_with_db(db):
            result_local = await rate_limiter.check_rate_limit(
                ip=client_ip,
                endpoint=endpoint,
                limit_type=limit_type,
                db=db,
            )
            if not result_local.allowed:
                await safe_record_security_event(
                    db,
                    event_type=SecurityEventType.RATE_LIMIT_EXCEEDED,
                    ip_address=client_ip,
                    user_agent=request.headers.get("user-agent", None),
                    user_email=None,
                    endpoint=endpoint,
                    details={
                        "limit_type": limit_type,
                        "attempts": result_local.attempts,
                        "limit": result_local.limit,
                        "retry_after": result_local.retry_after,
                    },
                )

                return result_local, self._rate_limited_response(endpoint, limit_type, result_local)

            return result_local, None

        try:
            # Always use a dedicated session that commits its own writes. The
            # request-scoped session owned by DBSessionMiddleware is rolled back
            # on any >=400 response (e.g. a failed login 401), which would undo
            # the attempt-counter increment and the RATE_LIMIT_EXCEEDED audit
            # write — defeating brute-force protection. Rate-limit bookkeeping
            # must persist independently of the request's final status.
            session_factory = get_async_db_session_factory()
            async with session_factory() as db:
                try:
                    result, blocked_resp = await _check_with_db(db)
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise

        except Exception as e:
            # Fail-closed on auth-critical paths to prevent brute-force during
            # backend instability; fail-open on general traffic to avoid outages.
            if limit_type in self.fail_closed_limit_types:
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
            logger.error(
                f"RateLimitMiddleware pass-through due to error: {e}",
                extra={"client_ip": client_ip, "endpoint": endpoint},
                exc_info=True,
            )
            return await call_next(request)

        if blocked_resp is not None:
            return blocked_resp

        response = await call_next(request)
        self._attach_rate_limit_headers(response, result)
        return response

    def _rate_limited_response(self, endpoint: str, limit_type: str, result) -> Response:
        # Special handling for OAuth starts to redirect to login with message.
        # Do not apply redirect for providers listing; return standard 429 instead.
        if "/auth/oauth" in endpoint and not endpoint.startswith("/api/v1/auth/oauth/providers"):
            login_url = (
                f"{settings.FRONTEND_URL}/login?error=Too%20many%20attempts.%20Try%20again%20later"
            )
            response = RedirectResponse(url=login_url, status_code=303)
        else:
            body = {
                "detail": f"Rate limit exceeded. Try again in {result.retry_after} seconds.",
                "rate_limit": {
                    "limit": result.limit,
                    "remaining": max(0, result.limit - result.attempts),
                    "reset": int(result.reset_time.timestamp()),
                    "retry_after": result.retry_after,
                    "type": limit_type,
                },
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
        response.headers["X-RateLimit-Limit"] = str(result.limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, result.limit - result.attempts))
        response.headers["X-RateLimit-Reset"] = str(int(result.reset_time.timestamp()))

    def _get_limit_type(self, endpoint: str, method: str) -> str:
        """Determine rate limit type based on endpoint and method."""

        # Authentication endpoints - stricter limits
        ep = endpoint.lower()
        # Treat OAuth providers list as general traffic, not login attempts
        if ep.startswith("/api/v1/auth/oauth/providers"):
            return "requests_per_minute"
        # All other OAuth flows and callbacks are considered login attempts
        if (
            ("/auth/" in ep and "login" in ep)
            or "/auth/callback/" in ep
            or ("/auth/oauth" in ep and not ep.startswith("/api/v1/auth/oauth/providers"))
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
