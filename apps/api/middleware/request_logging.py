# apps/api/middleware/request_logging.py

"""Request timing, metrics, and structured logging middleware."""

import logging
import time
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from core.observability import track_request
from core.rate_limiting import get_client_ip
from middleware.utils import _sanitize_headers_for_logging

logger = logging.getLogger(__name__)


def _endpoint_template_for_metrics(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if isinstance(route_path, str) and route_path:
        return route_path

    return "unmatched"


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for request timing and structured logging."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Log request timing and details."""
        start_time = time.perf_counter()
        client_ip = get_client_ip(request)
        try:
            response = await call_next(request)
        except Exception:
            self._record_request(
                request,
                client_ip,
                500,
                time.perf_counter() - start_time,
                include_exc_info=True,
            )
            raise

        process_time = time.perf_counter() - start_time
        self._record_request(request, client_ip, response.status_code, process_time)
        response.headers["X-Process-Time"] = str(process_time)
        return response

    def _record_request(
        self,
        request: Request,
        client_ip: str,
        status_code: int,
        process_time: float,
        include_exc_info: bool = False,
    ) -> None:
        workspace_id = request.headers.get("x-workspace")

        try:
            track_request(
                method=request.method,
                endpoint=_endpoint_template_for_metrics(request),
                status_code=status_code,
                duration=process_time,
            )
        except Exception:
            logger.warning("Failed to track request metrics", exc_info=True)

        log_data = {
            "method": request.method,
            "url": request.url.path or "/",
            "has_query_params": bool(request.url.query),
            "client_ip": client_ip,
            "status_code": status_code,
            "process_time": round(process_time, 4),
            "user_agent": request.headers.get("user-agent", ""),
            "headers": _sanitize_headers_for_logging(request.headers),
            "request_id": request.scope.get("request_id") or request.headers.get("x-request-id"),
            "workspace_id": workspace_id,
        }

        if status_code >= 500:
            logger.error("Request failed", extra=log_data, exc_info=include_exc_info)
        elif status_code >= 400:
            logger.warning("Client error", extra=log_data)
        else:
            logger.info("Request completed", extra=log_data)
