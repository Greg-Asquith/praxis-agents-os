# apps/api/tests/middleware/test_request_log_redaction.py

"""Anonymous artifact tokens never enter request logs."""

from unittest.mock import Mock

import pytest
from fastapi import Response
from starlette.requests import Request
from starlette.routing import Route

from core.exceptions.exception_handlers import app_exception_handler
from core.exceptions.general import NotFoundError
from core.rate_limiting import normalize_endpoint
from middleware.request_logging import RequestLoggingMiddleware


async def _endpoint() -> Response:
    return Response()


def test_shared_artifact_request_logs_the_route_template(monkeypatch) -> None:
    token = "secret-token-" + ("x" * 32)
    route = Route("/artifacts/shared/{token}", _endpoint)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "https",
            "path": f"/artifacts/shared/{token}",
            "raw_path": f"/artifacts/shared/{token}".encode(),
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 443),
            "route": route,
        }
    )
    middleware = RequestLoggingMiddleware(lambda _scope, _receive, _send: None)
    info = Mock()
    monkeypatch.setattr("middleware.request_logging.logger.info", info)
    middleware._record_request(request, "127.0.0.1", 200, 0.01)
    log_data = info.call_args.kwargs["extra"]
    assert log_data["url"] == "/artifacts/shared/{token}"
    assert token not in str(log_data)


@pytest.mark.asyncio
async def test_shared_artifact_exception_logs_redact_the_token(monkeypatch) -> None:
    token = "secret-token-" + ("y" * 32)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "https",
            "path": f"/artifacts/shared/{token}",
            "raw_path": f"/artifacts/shared/{token}".encode(),
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 443),
        }
    )
    log = Mock()
    monkeypatch.setattr("core.exceptions.exception_handlers.logger.log", log)
    response = await app_exception_handler(request, NotFoundError("Share not found"))
    assert response.status_code == 404
    log_data = log.call_args.kwargs["extra"]
    assert log_data["path"] == "/artifacts/shared/{token}"
    assert token not in str(log_data)


def test_shared_artifact_rate_limit_keys_redact_and_collapse_tokens() -> None:
    first = "a" * 43
    second = "b" * 43
    assert normalize_endpoint(f"/artifacts/shared/{first}") == "/artifacts/shared/{token}"
    assert normalize_endpoint(f"/artifacts/shared/{second}") == "/artifacts/shared/{token}"
