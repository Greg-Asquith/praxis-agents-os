"""Retry-After handling and typed provider HTTP failures."""

import httpx2
import pytest

from core.exceptions.integration import IntegrationAuthError, IntegrationRateLimitError
from core.settings import settings
from services.integrations import http as integration_http

pytestmark = pytest.mark.asyncio


async def test_retry_after_is_honored_capped_and_bounded(monkeypatch) -> None:
    calls = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(429, headers={"Retry-After": "999"}, request=request)

    original_client = httpx2.AsyncClient
    transport = httpx2.MockTransport(handler)
    monkeypatch.setattr(
        integration_http.httpx2,
        "AsyncClient",
        lambda: original_client(transport=transport),
    )
    monkeypatch.setattr(settings, "INTEGRATIONS_HTTP_RETRY_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(settings, "INTEGRATIONS_HTTP_RETRY_AFTER_CAP_SECONDS", 7)
    sleeps = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(integration_http.asyncio, "sleep", fake_sleep)
    with pytest.raises(IntegrationRateLimitError):
        await integration_http.request_with_retries(
            "GET",
            "https://provider.example/resource",
            operation="read_resource",
            provider_key="example",
        )
    assert calls == 3
    assert sleeps == [7, 7]


async def test_401_maps_without_retry(monkeypatch) -> None:
    calls = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(401, request=request)

    original_client = httpx2.AsyncClient
    transport = httpx2.MockTransport(handler)
    monkeypatch.setattr(
        integration_http.httpx2,
        "AsyncClient",
        lambda: original_client(transport=transport),
    )
    with pytest.raises(IntegrationAuthError):
        await integration_http.request_with_retries(
            "POST",
            "https://provider.example/token",
            operation="refresh",
            provider_key="example",
        )
    assert calls == 1


async def test_http_date_retry_after_parser() -> None:
    request = httpx2.Request("GET", "https://provider.example")
    response = httpx2.Response(
        503,
        headers={"Retry-After": "Fri, 10 Jul 2099 12:00:00 GMT"},
        request=request,
    )
    assert integration_http._retry_after_seconds(response) > 0
