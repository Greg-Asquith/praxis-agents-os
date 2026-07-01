# apps/api/middleware/csrf.py

"""CSRF protection middleware for cookie-authenticated requests."""

import logging
from collections.abc import Callable
from urllib.parse import urlparse

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from core.database import get_async_db_session_factory
from core.exceptions.auth import AuthorizationError
from core.rate_limiting import get_client_ip
from core.settings import settings
from services.security import SecurityEventType, safe_record_security_event
from utils.security import generate_csrf_token, verify_csrf_token

logger = logging.getLogger(__name__)


def _cookie_name_count(request: Request, name: str) -> int:
    raw_cookie_header = request.headers.get("cookie") or ""
    return sum(1 for part in raw_cookie_header.split(";") if part.strip().startswith(f"{name}="))


class CSRFMiddleware(BaseHTTPMiddleware):
    """Session-bound, HMAC-signed CSRF protection for cookie-based auth.

    Defence layers (in order):
    1. **Origin / Referer check** — rejects cross-origin unsafe requests from
       browsers that send an ``Origin`` or ``Referer`` header.
    2. **Signed token verification** — the ``X-CSRF-Token`` header must carry a
       token whose HMAC signature and embedded session-hash prefix match the
       current ``session`` cookie.  This prevents both cookie-injection and
       plain replay attacks.

    Enforcement only applies when a ``session`` cookie is present (i.e. the
    request is cookie-authenticated). Exempt routes are skipped entirely.
    """

    def __init__(self, app, exempt_paths: list | None = None):
        super().__init__(app)
        self.exempt_paths = exempt_paths or [
            # Pre-auth session creation endpoints must tolerate stale local auth cookies. They are JSON/CORS-gated and issue a new session.
            "/api/v1/auth/register",
            "/api/v1/auth/login",
            "/api/v1/auth/oauth",
            # Direct-upload URLs are HMAC-signed storage capabilities. They mirror cloud signed uploads, which bypass app cookies and CSRF middleware entirely.
            "/api/v1/storage/upload",
            # Health/metrics are GET-only; keep list accurate for clarity
            "/api/health",
            "/api/metrics",
        ]

    def _is_exempt(self, path: str) -> bool:
        return any(path.startswith(p) for p in self.exempt_paths)

    @staticmethod
    def _has_cookie_session(request: Request) -> bool:
        return bool(request.cookies.get("session"))

    def _should_enforce_csrf(self, request: Request) -> bool:
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return False
        if self._is_exempt(request.url.path):
            return False
        return self._has_cookie_session(request)

    # ------------------------------------------------------------------
    # Origin / Referer validation
    # ------------------------------------------------------------------

    @staticmethod
    def _check_origin(request: Request) -> None:
        """Reject cross-origin unsafe requests based on Origin or Referer.

        If neither header is present we allow the request through — some
        legitimate clients (e.g. server-side Next.js ``apiFetch``) may not
        send either header.  The signed-token check that follows provides
        the hard guarantee.
        """
        origin = request.headers.get("origin")
        referer = request.headers.get("referer")

        # Build allowed origin set from CORS config + frontend URL
        allowed: set[str] = set()
        for o in settings.cors_origins_list:
            allowed.add(o.rstrip("/"))
        if settings.FRONTEND_URL:
            allowed.add(settings.FRONTEND_URL.rstrip("/"))

        if origin:
            if origin.rstrip("/") not in allowed:
                raise AuthorizationError(
                    message="CSRF origin rejected",
                    details={"reason": "origin not allowed"},
                )
            return  # Origin present and valid — pass

        if referer:
            # Extract scheme + host from referer
            parsed = urlparse(referer)
            referer_origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
            if referer_origin not in allowed:
                raise AuthorizationError(
                    message="CSRF referer rejected",
                    details={"reason": "referer origin not allowed"},
                )
            return  # Referer present and valid — pass

        # Neither header present — fall through to token check

    # ------------------------------------------------------------------
    # Security-event recording
    # ------------------------------------------------------------------

    async def _record_rejection(self, request: Request, *, reason: str) -> None:
        """Persist a CSRF rejection as a security event, best-effort.

        Uses a dedicated committed session because the request-scoped session is
        rolled back on the 403 response, and runs in its own try/except so a
        logging failure can never turn a rejected request into a 500.
        """
        try:
            session_factory = get_async_db_session_factory()
            async with session_factory() as db:
                await safe_record_security_event(
                    db,
                    event_type=SecurityEventType.CSRF_VALIDATION_FAILED,
                    ip_address=get_client_ip(request),
                    endpoint=request.url.path,
                    user_agent=request.headers.get("user-agent"),
                    request_id=request.scope.get("request_id"),
                    details={"reason": reason, "method": request.method},
                )
                await db.commit()
        except Exception:
            logger.error("Failed to record CSRF security event", exc_info=True)

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if self._should_enforce_csrf(request):
            try:
                # Layer 1: Origin / Referer
                self._check_origin(request)

                # Layer 2: Signed session-bound token
                header_token = request.headers.get("x-csrf-token")
                session_token = request.cookies.get("session")

                if not header_token:
                    raise AuthorizationError(
                        message="CSRF token missing",
                        details={"reason": "X-CSRF-Token header missing"},
                    )

                # Verify the token is signed and bound to this session
                verify_csrf_token(csrf_token=header_token, session_token=session_token)

            except AuthorizationError as exc:
                # Return a proper 403 JSON response instead of letting the
                # exception bubble up as an unhandled 500 from BaseHTTPMiddleware.
                await self._record_rejection(
                    request,
                    reason=exc.details.get("reason") or exc.message,
                )
                logger.warning(
                    "CSRF validation failed: %s",
                    exc.message,
                    extra={
                        "method": request.method,
                        "path": request.url.path,
                        "session_cookie_count": _cookie_name_count(request, "session"),
                        "csrf_cookie_count": _cookie_name_count(request, "csrf"),
                    },
                )
                return JSONResponse(
                    status_code=403,
                    content={
                        "type": "authorization_error",
                        "title": "CSRF validation failed",
                        "status": 403,
                        "detail": exc.message,
                        "method": request.method,
                        "path": request.url.path,
                        "has_csrf_header": bool(request.headers.get("x-csrf-token")),
                        **exc.details,
                    },
                )

        response = await call_next(request)

        # Auto-refresh the CSRF cookie on every authenticated response so the
        # token never expires while the session is still active.
        session_token = request.cookies.get("session")
        if session_token and response.status_code < 400:
            fresh_token = generate_csrf_token(session_token)
            cookie_domain = settings.COOKIE_DOMAIN or None
            response.set_cookie(
                key="csrf",
                value=fresh_token,
                httponly=False,
                secure=settings.SECURE_COOKIES,
                samesite="lax",
                max_age=settings.SESSION_DURATION_DAYS * 24 * 60 * 60,
                domain=cookie_domain,
            )

        return response
