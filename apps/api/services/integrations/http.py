# apps/api/services/integrations/http.py

"""Retrying httpx2 seam for integration APIs.

This is deliberately separate from the pydantic-ai provider transport: that
client uses plain httpx and LLM-specific retry settings, while application
integration calls use httpx2 and the integration policy below.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Any

import httpx2

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationConnectionError,
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
    kwargs: dict[str, Any],
) -> httpx2.Response:
    last_status: int | None = None
    last_error: Exception | None = None
    retryable = policy in {
        IntegrationRequestPolicy.READ,
        IntegrationRequestPolicy.IDEMPOTENT_WRITE,
    }

    for attempt in range(settings.INTEGRATIONS_HTTP_RETRY_MAX_ATTEMPTS):
        last_status = None
        last_error = None
        response: httpx2.Response | None = None
        try:
            response = await client.request(method, url, **kwargs)
            if response.status_code < 400:
                return response
            last_status = response.status_code
            if response.status_code == 401:
                raise IntegrationAuthError(
                    "Integration authentication failed",
                    provider_key=provider_key,
                    operation=operation,
                    failure_disposition=IntegrationFailureDisposition.REJECTED,
                )
            if response.status_code == 403:
                raise IntegrationPermissionError(
                    "Integration operation was denied",
                    provider_key=provider_key,
                    operation=operation,
                    failure_disposition=IntegrationFailureDisposition.REJECTED,
                )
            if response.status_code == 404:
                raise IntegrationNotFoundError(
                    "Integration resource was not found",
                    provider_key=provider_key,
                    operation=operation,
                    failure_disposition=IntegrationFailureDisposition.REJECTED,
                )
            if 400 <= response.status_code < 500 and response.status_code != 429:
                detail = (
                    validation_error_detail(response)
                    if validation_error_detail is not None
                    else None
                )
                raise IntegrationValidationError(
                    detail or "Integration request was rejected",
                    provider_key=provider_key,
                    operation=operation,
                    failure_disposition=IntegrationFailureDisposition.REJECTED,
                )
            last_error = httpx2.HTTPStatusError(
                "Retryable integration response",
                request=response.request,
                response=response,
            )
            retryable = policy is not IntegrationRequestPolicy.MUTATION
        except asyncio.CancelledError as exc:
            if policy is IntegrationRequestPolicy.MUTATION:
                exc.failure_disposition = IntegrationFailureDisposition.AMBIGUOUS
            raise
        except (
            IntegrationAuthError,
            IntegrationNotFoundError,
            IntegrationPermissionError,
            IntegrationValidationError,
        ):
            raise
        except (TimeoutError, httpx2.RequestError) as exc:
            last_error = exc
            retryable = policy is not IntegrationRequestPolicy.MUTATION

        if not retryable or attempt + 1 >= settings.INTEGRATIONS_HTTP_RETRY_MAX_ATTEMPTS:
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
        "original_error": last_error,
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


def _retry_after_seconds(response: httpx2.Response) -> float | None:
    if response.status_code not in {429, 503}:
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
