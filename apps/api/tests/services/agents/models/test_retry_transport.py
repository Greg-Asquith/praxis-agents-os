# apps/api/tests/services/agents/models/test_retry_transport.py

"""Provider HTTP retry transport behavior."""

import httpx
import pytest

from core.settings import settings
from services.agents.models.utils import _build_retrying_http_client

pytestmark = pytest.mark.asyncio


def _fast_retry_settings(monkeypatch, *, attempts: int) -> None:
    monkeypatch.setattr(settings, "LLM_HTTP_RETRY_MAX_ATTEMPTS", attempts)
    monkeypatch.setattr(settings, "LLM_HTTP_RETRY_MAX_WAIT_SECONDS", 0.001)
    monkeypatch.setattr(settings, "LLM_HTTP_RETRY_TOTAL_WAIT_CAP_SECONDS", 0.001)


async def test_retrying_http_client_retries_429_then_succeeds(monkeypatch) -> None:
    _fast_retry_settings(monkeypatch, attempts=2)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, request=request)
        return httpx.Response(200, json={"ok": True}, request=request)

    client = _build_retrying_http_client(wrapped=httpx.MockTransport(handler))
    try:
        response = await client.get("https://provider.example/test")
    finally:
        await client.aclose()

    assert response.status_code == 200
    assert calls == 2


async def test_retrying_http_client_does_not_retry_non_transient_401(monkeypatch) -> None:
    _fast_retry_settings(monkeypatch, attempts=3)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, request=request)

    client = _build_retrying_http_client(wrapped=httpx.MockTransport(handler))
    try:
        response = await client.get("https://provider.example/test")
    finally:
        await client.aclose()

    assert response.status_code == 401
    assert calls == 1


async def test_retrying_http_client_exhaustion_reraises(monkeypatch) -> None:
    _fast_retry_settings(monkeypatch, attempts=3)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, request=request)

    client = _build_retrying_http_client(wrapped=httpx.MockTransport(handler))
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await client.get("https://provider.example/test")
    finally:
        await client.aclose()

    assert calls == 3
