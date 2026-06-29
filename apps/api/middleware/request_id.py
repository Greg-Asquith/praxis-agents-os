# apps/api/middleware/request_id.py

"""Request ID propagation middleware."""

import logging
import re
import uuid
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from core.logging import clear_trace_id, set_trace_id

logger = logging.getLogger(__name__)

# Accept only safe, bounded correlation IDs; anything else is replaced with a
# generated UUID to prevent log injection and unbounded header values.
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach/propagate a correlation ID via `X-Request-ID`.

    Also sets the trace_id context variable for structured logging correlation.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        incoming = request.headers.get("x-request-id")
        req_id = incoming if incoming and _REQUEST_ID_RE.match(incoming) else str(uuid.uuid4())
        # Stash in scope for downstream consumers
        request.scope["request_id"] = req_id

        # Set trace_id in context for logging correlation
        set_trace_id(req_id)

        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = req_id
            return response
        finally:
            # Clear trace_id after request completes
            clear_trace_id()
