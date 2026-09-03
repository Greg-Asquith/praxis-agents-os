# apps/api/services/integrations/http.py

"""Retrying httpx2 seam for integration APIs.

This is deliberately separate from the pydantic-ai provider transport: that
client uses plain httpx and LLM-specific retry settings, while application
integration calls use httpx2 and the integration policy below.
"""

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from contextlib import AbstractAsyncContextManager, contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Any

import httpx2

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationConnectionError,
    IntegrationError,
    IntegrationFailureDisposition,
    IntegrationNotFoundError,
    IntegrationPermissionError,
    IntegrationRateLimitError,
    IntegrationTimeoutError,
    IntegrationValidationError,
)
from core.settings import settings


class IntegrationRequestPolicy(StrEnum):
    """Semantic retry policy for one integration request."""

    READ = "read"
    IDEMPOTENT_WRITE = "idempotent_write"
    MUTATION = "mutation"


@dataclass
class TransportAttemptCounter:
    """Accumulates logical request and dispatched attempt counts for one operation."""

    requests: int = 0
    attempts: int = 0


@dataclass(frozen=True)
class _SuccessfulAttempt[T]:
    value: T


@dataclass(frozen=True)
class _RetryableAttempt:
    response: httpx2.Response


type _AttemptResult[T] = _SuccessfulAttempt[T] | _RetryableAttempt


_attempt_counter: ContextVar[TransportAttemptCounter | None] = ContextVar(
    "integration_transport_attempts", default=None
)


@contextmanager
def track_transport_attempts() -> Iterator[TransportAttemptCounter]:
    """Counts provider requests and retry attempts issued within this context."""
    counter = TransportAttemptCounter()
    token = _attempt_counter.set(counter)
    try:
        yield counter
    finally:
        _attempt_counter.reset(token)


async def resolve_before_dispatch[T](resolve: Callable[[], Awaitable[T]]) -> T:
    """Resolve request prerequisites and classify failures as pre-dispatch."""
    try:
        return await resolve()
    except Exception as exc:
        exc.failure_disposition = IntegrationFailureDisposition.NOT_DISPATCHED
        raise


async def request_with_retries(
    method: str,
    url: str,
    *,
    operation: str,
    provider_key: str,
    policy: IntegrationRequestPolicy,
    client: httpx2.AsyncClient | None = None,
    validation_error_detail: Callable[[httpx2.Response], str | None] | None = None,
    response_error_mapper: Callable[[httpx2.Response], IntegrationError | None] | None = None,
    attempt_context: Callable[[], AbstractAsyncContextManager[None]] | None = None,
    **kwargs: Any,
) -> httpx2.Response:
    """Issue one bounded provider request and map failures to typed errors."""
    if not isinstance(policy, IntegrationRequestPolicy):
        raise TypeError("policy must be an IntegrationRequestPolicy")
    kwargs.setdefault("timeout", settings.INTEGRATIONS_HTTP_TIMEOUT_SECONDS)
    if client is not None:
        return await _request_with_client(
            client,
            method,
            url,
            operation=operation,
            provider_key=provider_key,
            policy=policy,
            validation_error_detail=validation_error_detail,
            response_error_mapper=response_error_mapper,
            attempt_context=attempt_context,
            kwargs=kwargs,
        )
    async with httpx2.AsyncClient() as owned_client:
        return await _request_with_client(
            owned_client,
            method,
            url,
            operation=operation,
            provider_key=provider_key,
            policy=policy,
            validation_error_detail=validation_error_detail,
            response_error_mapper=response_error_mapper,
            attempt_context=attempt_context,
            kwargs=kwargs,
        )


async def consume_stream_with_retries[T](
    method: str,
    url: str | httpx2.URL,
    *,
    operation: str,
    provider_key: str,
    policy: IntegrationRequestPolicy,
    consume: Callable[[httpx2.Response], Awaitable[T]],
    client: httpx2.AsyncClient | None = None,
    validation_error_detail: Callable[[httpx2.Response], str | None] | None = None,
    response_error_mapper: Callable[[httpx2.Response], IntegrationError | None] | None = None,
    attempt_context: Callable[[], AbstractAsyncContextManager[None]] | None = None,
    include_original_error: bool = True,
    **kwargs: Any,
) -> T:
    """Consume one streamed response with bounded retries and typed failures."""
    if not isinstance(policy, IntegrationRequestPolicy):
        raise TypeError("policy must be an IntegrationRequestPolicy")
    kwargs.setdefault("timeout", settings.INTEGRATIONS_HTTP_TIMEOUT_SECONDS)
    if client is not None:
        return await _consume_stream_with_client(
            client,
            method,
            url,
            operation=operation,
            provider_key=provider_key,
            policy=policy,
            consume=consume,
            validation_error_detail=validation_error_detail,
            response_error_mapper=response_error_mapper,
            attempt_context=attempt_context,
            include_original_error=include_original_error,
            kwargs=kwargs,
        )
    async with httpx2.AsyncClient() as owned_client:
        return await _consume_stream_with_client(
            owned_client,
            method,
            url,
            operation=operation,
            provider_key=provider_key,
            policy=policy,
            consume=consume,
            validation_error_detail=validation_error_detail,
            response_error_mapper=response_error_mapper,
            attempt_context=attempt_context,
            include_original_error=include_original_error,
            kwargs=kwargs,
        )


async def _request_with_client(
    client: httpx2.AsyncClient,
    method: str,
    url: str,
    *,
    operation: str,
    provider_key: str,
    policy: IntegrationRequestPolicy,
    validation_error_detail: Callable[[httpx2.Response], str | None] | None,
    response_error_mapper: Callable[[httpx2.Response], IntegrationError | None] | None,
    attempt_context: Callable[[], AbstractAsyncContextManager[None]] | None,
    kwargs: dict[str, Any],
) -> httpx2.Response:
    async def dispatch() -> _AttemptResult[httpx2.Response]:
        guard = attempt_context() if attempt_context is not None else nullcontext()
        async with guard:
            response = await client.request(method, url, **kwargs)
        if response.status_code < 400:
            return _SuccessfulAttempt(response)
        _raise_response_error(
            response,
            operation=operation,
            provider_key=provider_key,
            validation_error_detail=validation_error_detail,
            response_error_mapper=response_error_mapper,
        )
        return _RetryableAttempt(response)

    return await _run_with_retries(
        dispatch,
        operation=operation,
        provider_key=provider_key,
        policy=policy,
    )


async def _consume_stream_with_client[T](
    client: httpx2.AsyncClient,
    method: str,
    url: str | httpx2.URL,
    *,
    operation: str,
    provider_key: str,
    policy: IntegrationRequestPolicy,
    consume: Callable[[httpx2.Response], Awaitable[T]],
    validation_error_detail: Callable[[httpx2.Response], str | None] | None,
    response_error_mapper: Callable[[httpx2.Response], IntegrationError | None] | None,
    attempt_context: Callable[[], AbstractAsyncContextManager[None]] | None,
    include_original_error: bool,
    kwargs: dict[str, Any],
) -> T:
    async def dispatch() -> _AttemptResult[T]:
        guard = attempt_context() if attempt_context is not None else nullcontext()
        async with guard, client.stream(method, url, **kwargs) as response:
            if response.status_code < 400:
                return _SuccessfulAttempt(await consume(response))
            _raise_response_error(
                response,
                operation=operation,
                provider_key=provider_key,
                validation_error_detail=validation_error_detail,
                response_error_mapper=response_error_mapper,
            )
            return _RetryableAttempt(response)

    return await _run_with_retries(
        dispatch,
        operation=operation,
        provider_key=provider_key,
        policy=policy,
        include_original_error=include_original_error,
    )


async def _run_with_retries[T](
    dispatch: Callable[[], Awaitable[_AttemptResult[T]]],
    *,
    operation: str,
    provider_key: str,
    policy: IntegrationRequestPolicy,
    include_original_error: bool = True,
) -> T:
    last_status: int | None = None
    last_error: Exception | None = None
    can_retry = policy in {
        IntegrationRequestPolicy.READ,
        IntegrationRequestPolicy.IDEMPOTENT_WRITE,
    }
    counter = _attempt_counter.get()
    if counter is not None:
        counter.requests += 1

    for attempt in range(settings.INTEGRATIONS_HTTP_RETRY_MAX_ATTEMPTS):
        last_status = None
        last_error = None
        response: httpx2.Response | None = None
        if counter is not None:
            counter.attempts += 1
        try:
            result = await dispatch()
            if isinstance(result, _SuccessfulAttempt):
                return result.value
            response = result.response
            last_status = response.status_code
            last_error = httpx2.HTTPStatusError(
                "Retryable integration response",
                request=response.request,
                response=response,
            )
        except asyncio.CancelledError as exc:
            if policy is IntegrationRequestPolicy.MUTATION:
                exc.failure_disposition = IntegrationFailureDisposition.AMBIGUOUS
            raise
        except (
            IntegrationAuthError,
            IntegrationNotFoundError,
            IntegrationPermissionError,
            IntegrationRateLimitError,
            IntegrationValidationError,
        ):
            raise
        except (TimeoutError, httpx2.RequestError) as exc:
            last_error = exc

        if not can_retry or attempt + 1 >= settings.INTEGRATIONS_HTTP_RETRY_MAX_ATTEMPTS:
            break
        retry_after = _retry_after_seconds(response) if response is not None else None
        delay = (
            min(retry_after, settings.INTEGRATIONS_HTTP_RETRY_AFTER_CAP_SECONDS)
            if retry_after is not None
            else settings.INTEGRATIONS_HTTP_RETRY_BACKOFF_FACTOR * (2**attempt)
        )
        await asyncio.sleep(delay)

    context = {
        "provider_key": provider_key,
        "operation": operation,
        "original_error": last_error if include_original_error else None,
        "failure_disposition": (
            IntegrationFailureDisposition.AMBIGUOUS
            if policy is IntegrationRequestPolicy.MUTATION
            else IntegrationFailureDisposition.REJECTED
        ),
    }
    if last_status == 429:
        raise IntegrationRateLimitError("Integration rate limit exceeded", **context)
    if isinstance(last_error, (TimeoutError, httpx2.TimeoutException)):
        raise IntegrationTimeoutError("Integration request timed out", **context)
    raise IntegrationConnectionError("Integration provider request failed", **context)


def _raise_response_error(
    response: httpx2.Response,
    *,
    operation: str,
    provider_key: str,
    validation_error_detail: Callable[[httpx2.Response], str | None] | None,
    response_error_mapper: Callable[[httpx2.Response], IntegrationError | None] | None,
) -> None:
    if response_error_mapper is not None:
        mapped_error = response_error_mapper(response)
        if mapped_error is not None:
            raise mapped_error
    context = {
        "provider_key": provider_key,
        "operation": operation,
        "failure_disposition": IntegrationFailureDisposition.REJECTED,
    }
    if response.status_code == 401:
        raise IntegrationAuthError("Integration authentication failed", **context)
    if response.status_code == 403:
        raise IntegrationPermissionError("Integration operation was denied", **context)
    if response.status_code == 404:
        raise IntegrationNotFoundError("Integration resource was not found", **context)
    if 400 <= response.status_code < 500 and response.status_code != 429:
        detail = validation_error_detail(response) if validation_error_detail is not None else None
        raise IntegrationValidationError(
            detail or "Integration request was rejected",
            **context,
        )


def _retry_after_seconds(response: httpx2.Response) -> float | None:
    if response.status_code not in {429, 503, 529}:
        return None
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(raw)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())
