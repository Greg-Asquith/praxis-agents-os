"""Retry-After handling and typed provider HTTP failures."""

import asyncio
from unittest.mock import AsyncMock

import httpx2
import pytest

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationConnectionError,
    IntegrationFailureDisposition,
    IntegrationRateLimitError,
    IntegrationTimeoutError,
)
from core.settings import settings
from services.integrations import http as integration_http
from services.integrations.http import IntegrationRequestPolicy

pytestmark = pytest.mark.asyncio


async def test_pre_dispatch_resolution_marks_failures_without_wrapping() -> None:
    error = RuntimeError("credential unavailable")

    async def resolve() -> str:
        raise error

    with pytest.raises(RuntimeError) as exc_info:
        await integration_http.resolve_before_dispatch(resolve)

    assert exc_info.value is error
    assert error.failure_disposition is IntegrationFailureDisposition.NOT_DISPATCHED


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
            policy=IntegrationRequestPolicy.READ,
        )
    assert calls == 3
    assert sleeps == [7, 7]


async def test_transport_attempts_are_counted_across_retries(monkeypatch) -> None:
    responses = iter([503, 503, 200])

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(next(responses, 200), request=request)

    original_client = httpx2.AsyncClient
    transport = httpx2.MockTransport(handler)
    monkeypatch.setattr(
        integration_http.httpx2,
        "AsyncClient",
        lambda: original_client(transport=transport),
    )
    monkeypatch.setattr(settings, "INTEGRATIONS_HTTP_RETRY_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(integration_http.asyncio, "sleep", AsyncMock())

    with integration_http.track_transport_attempts() as counter:
        response = await integration_http.request_with_retries(
            "GET",
            "https://provider.example/resource",
            operation="read_resource",
            provider_key="example",
            policy=IntegrationRequestPolicy.READ,
        )
        await integration_http.request_with_retries(
            "GET",
            "https://provider.example/resource",
            operation="read_resource",
            provider_key="example",
            policy=IntegrationRequestPolicy.READ,
        )

    assert response.status_code == 200
    assert counter.requests == 2
    assert counter.attempts == 4

    # Outside the tracking context, requests accumulate nothing.
    await integration_http.request_with_retries(
        "GET",
        "https://provider.example/resource",
        operation="read_resource",
        provider_key="example",
        policy=IntegrationRequestPolicy.READ,
    )
    assert counter.requests == 2
    assert counter.attempts == 4


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
    with pytest.raises(IntegrationAuthError) as exc_info:
        await integration_http.request_with_retries(
            "POST",
            "https://provider.example/token",
            operation="refresh",
            provider_key="example",
            policy=IntegrationRequestPolicy.MUTATION,
        )
    assert calls == 1
    assert exc_info.value.failure_disposition is IntegrationFailureDisposition.REJECTED


async def test_http_date_retry_after_parser() -> None:
    status_code = 429
    request = httpx2.Request("GET", "https://provider.example")
    response = httpx2.Response(
        status_code,
        headers={"Retry-After": "Fri, 10 Jul 2099 12:00:00 GMT"},
        request=request,
    )
    assert integration_http._retry_after_seconds(response) > 0


@pytest.mark.parametrize(
    ("failure", "expected_error", "expected_disposition"),
    [
        (503, IntegrationConnectionError, IntegrationFailureDisposition.AMBIGUOUS),
        (
            httpx2.ConnectError("connect failed"),
            IntegrationConnectionError,
            IntegrationFailureDisposition.AMBIGUOUS,
        ),
        (
            httpx2.ReadTimeout("response timed out"),
            IntegrationTimeoutError,
            IntegrationFailureDisposition.AMBIGUOUS,
        ),
    ],
)
async def test_mutation_failures_are_attempted_once(
    monkeypatch,
    failure: int | httpx2.RequestError,
    expected_error: type[Exception],
    expected_disposition: IntegrationFailureDisposition,
) -> None:
    attempts = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        attempts += 1
        if isinstance(failure, int):
            return httpx2.Response(failure, request=request)
        failure.request = request
        raise failure

    original_client = httpx2.AsyncClient
    monkeypatch.setattr(
        integration_http.httpx2,
        "AsyncClient",
        lambda: original_client(transport=httpx2.MockTransport(handler)),
    )
    monkeypatch.setattr(settings, "INTEGRATIONS_HTTP_RETRY_MAX_ATTEMPTS", 3)

    with pytest.raises(expected_error) as exc_info:
        await integration_http.request_with_retries(
            "POST",
            "https://provider.example/mutate",
            operation="mutate",
            provider_key="example",
            policy=IntegrationRequestPolicy.MUTATION,
        )

    assert attempts == 1
    assert exc_info.value.failure_disposition is expected_disposition


async def test_read_post_retains_bounded_retry_behavior(monkeypatch) -> None:
    attempts = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal attempts
        attempts += 1
        return httpx2.Response(503 if attempts < 3 else 200, request=request)

    original_client = httpx2.AsyncClient
    monkeypatch.setattr(
        integration_http.httpx2,
        "AsyncClient",
        lambda: original_client(transport=httpx2.MockTransport(handler)),
    )
    monkeypatch.setattr(settings, "INTEGRATIONS_HTTP_RETRY_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(integration_http.asyncio, "sleep", AsyncMock())

    response = await integration_http.request_with_retries(
        "POST",
        "https://provider.example/query",
        operation="query",
        provider_key="example",
        policy=IntegrationRequestPolicy.READ,
    )

    assert response.status_code == 200
    assert attempts == 3


async def test_in_flight_mutation_cancellation_is_marked_ambiguous() -> None:
    class CancellingClient:
        async def request(self, *_args, **_kwargs):
            raise asyncio.CancelledError("cancelled in transport")

    with pytest.raises(asyncio.CancelledError) as exc_info:
        await integration_http.request_with_retries(
            "POST",
            "https://provider.example/mutate",
            operation="mutate",
            provider_key="example",
            policy=IntegrationRequestPolicy.MUTATION,
            client=CancellingClient(),  # type: ignore[arg-type]
        )

    assert exc_info.value.failure_disposition is IntegrationFailureDisposition.AMBIGUOUS
