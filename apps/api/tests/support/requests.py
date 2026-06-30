# apps/api/tests/support/requests.py

"""Request builders for service tests that record request context."""

from collections.abc import Mapping

from starlette.requests import Request


def build_test_request(
    *,
    path: str = "/test",
    method: str = "POST",
    headers: Mapping[str, str] | None = None,
) -> Request:
    """Build a minimal HTTP request suitable for service-layer audit tests."""
    raw_headers = [(b"host", b"testserver")]
    for name, value in (headers or {}).items():
        raw_headers.append((name.lower().encode(), value.encode()))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": raw_headers,
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "request_id": "test-request-id",
    }
    return Request(scope)
