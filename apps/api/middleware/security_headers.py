# apps/api/middleware/security_headers.py

"""Security header middleware for API responses."""

import logging
from collections.abc import Callable
from urllib.parse import urlsplit

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from core.settings import settings
from middleware.utils import _is_app_frame_path

logger = logging.getLogger(__name__)


def _origin_from_url(url: str | None) -> str | None:
    if not url:
        return None

    parsed = urlsplit(url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return None


def _frame_ancestors() -> str:
    ancestors = ["'self'"]
    candidates: list[str | None] = [
        getattr(settings, "FRONTEND_URL", None),
        getattr(settings, "frontend_base_url", None),
    ]
    candidates.extend(getattr(settings, "cors_origins_list", []) or [])

    for candidate in candidates:
        origin = _origin_from_url(candidate)
        if origin and origin not in ancestors:
            ancestors.append(origin)

    return " ".join(ancestors)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add standard security headers suitable for APIs."""

    def __init__(self, app):
        super().__init__(app)
        # Computed at app construction so it reflects the active settings.
        self._frame_ancestors = _frame_ancestors()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        is_app_frame = _is_app_frame_path(request.url.path)

        # Basic hardening headers
        if not is_app_frame:
            response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), camera=(), microphone=()"
        )
        if is_app_frame:
            response.headers.setdefault(
                "Content-Security-Policy",
                f"frame-ancestors {self._frame_ancestors}; base-uri 'none'; object-src 'none'",
            )
        else:
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
            )
        # HSTS (only when not in debug)
        if not settings.DEBUG:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=63072000; includeSubDomains; preload",
            )
        return response
