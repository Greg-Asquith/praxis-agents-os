# apps/api/middleware/artifact_host.py

"""Host isolation between the artifact serving surface and the API."""

from collections.abc import Callable
from urllib.parse import urlsplit

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from core.settings import settings
from middleware.utils import _is_artifact_serving_path


def _not_found_response() -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "type": "https://httpstatuses.com/404",
            "title": "Resource Not Found",
            "status": 404,
            "detail": "Not found",
        },
        media_type="application/problem+json",
    )


class ArtifactHostMiddleware(BaseHTTPMiddleware):
    """Partition routes between the artifact host and the API host.

    When ``ARTIFACT_ORIGIN`` is configured, requests to its host may only
    reach the cookie-free artifact serving surface, and every other host
    refuses that surface. This makes the origin split enforced by settings
    validation hold at request time instead of relying on DNS alone. Inactive
    when ``ARTIFACT_ORIGIN`` is empty (local serves both from APP_BASE_URL).
    """

    def __init__(self, app, artifact_origin: str | None = None):
        super().__init__(app)
        configured = artifact_origin if artifact_origin is not None else settings.ARTIFACT_ORIGIN
        self.artifact_host = (urlsplit(configured).hostname or "").lower() if configured else ""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self.artifact_host:
            return await call_next(request)
        is_artifact_host = (request.url.hostname or "").lower() == self.artifact_host
        if is_artifact_host != _is_artifact_serving_path(request.url.path):
            return _not_found_response()
        return await call_next(request)
