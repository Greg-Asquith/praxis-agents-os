# apps/api/middleware/body_size.py

"""Request body size limit middleware."""

import logging
from collections.abc import Callable
from typing import ClassVar

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from core.settings import settings
from middleware.utils import _base64_request_limit

logger = logging.getLogger(__name__)


def _problem_response(
    status_code: int, title: str, detail: str, **extra: int | str
) -> JSONResponse:
    problem = {
        "type": f"https://httpstatuses.com/{status_code}",
        "title": title,
        "status": status_code,
        "detail": detail,
        **extra,
    }
    return JSONResponse(
        status_code=status_code,
        content=problem,
        media_type="application/problem+json",
    )


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Enforce a global request body size limit with route-specific overrides.

    Checks Content-Length and enforces a streamed limit if missing.
    Supports route-specific limits via path_limits dict.
    """

    # Routes that need larger payloads (values in bytes).
    # Base64 payloads are ~33% larger than raw bytes, so include headroom.
    ROUTE_LIMITS: ClassVar[dict[str, int]] = {
        "/api/v1/example": _base64_request_limit(
            settings.MAX_FILE_SIZE_AI_IMAGE
        ),
        f"{settings.API_V1_PREFIX}/storage/upload": max(
            settings.MAX_FILE_SIZE_AGENT_FILE,
            settings.MAX_FILE_SIZE_DOCUMENT,
            settings.MAX_FILE_SIZE_AI_VIDEO,
        ),
    }

    def __init__(
        self,
        app,
        max_bytes: int | None = None,
        path_limits: dict[str, int] | None = None,
    ):
        super().__init__(app)
        self.max_bytes = max_bytes or settings.MAX_REQUEST_BODY_BYTES
        self.path_limits = {**self.ROUTE_LIMITS, **(path_limits or {})}

    def _get_limit_for_path(self, path: str) -> int:
        """Get the body size limit for a given path."""
        for route_path, limit in self.path_limits.items():
            if path.startswith(route_path):
                return limit
        return self.max_bytes

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip safe methods
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return await call_next(request)

        # Get route-specific limit
        effective_limit = self._get_limit_for_path(request.url.path)

        # Content-Length check
        cl = request.headers.get("content-length")
        try:
            content_length = int(cl) if cl is not None else None
            if content_length is not None and content_length < 0:
                raise ValueError
            if content_length is not None and content_length > effective_limit:
                return _problem_response(
                    status_code=413,
                    title="Request Body Too Large",
                    detail=f"Request body too large (>{effective_limit} bytes)",
                    max_bytes=effective_limit,
                )
        except ValueError:
            return _problem_response(
                status_code=400,
                title="Invalid Content-Length",
                detail="Invalid Content-Length header",
                field="Content-Length",
                reason="non-negative integer required",
            )

        # Streamed enforcement if no/invalid Content-Length. Raising through the
        # ASGI receive channel is unreliable (body-parsing machinery may catch
        # broad Exception), so flag overflow on the scope and terminate the
        # stream instead, then replace the response with 413 afterwards.
        received = 0
        receive = request.receive
        request.scope["_body_too_large"] = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body") or b"")
                if received > effective_limit:
                    request.scope["_body_too_large"] = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        request = Request(request.scope, receive=limited_receive)
        response = await call_next(request)
        if request.scope.get("_body_too_large"):
            return _problem_response(
                status_code=413,
                title="Request Body Too Large",
                detail=f"Request body too large (>{effective_limit} bytes)",
                max_bytes=effective_limit,
            )
        return response
