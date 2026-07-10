# apps/api/services/integrations/http.py

"""Retrying httpx2 seam for integration APIs.

This is deliberately separate from the pydantic-ai provider transport: that
client uses plain httpx and LLM-specific retry settings, while application
integration calls use httpx2 and the integration policy below.
"""

import asyncio
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx2

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationConnectionError,
    IntegrationPermissionError,
    IntegrationRateLimitError,
    IntegrationTimeoutError,
    IntegrationValidationError,
)
from core.settings import settings


async def request_with_retries(
    method: str,
    url: str,
    *,
    operation: str,
    provider_key: str,
    **kwargs: Any,
) -> httpx2.Response:
    """Issue one bounded provider request and map failures to typed errors."""
    kwargs.setdefault("timeout", settings.INTEGRATIONS_HTTP_TIMEOUT_SECONDS)
    last_status: int | None = None
    last_error: Exception | None = None

    async with httpx2.AsyncClient() as client:
        for attempt in range(settings.INTEGRATIONS_HTTP_RETRY_MAX_ATTEMPTS):
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
                    )
                if response.status_code == 403:
                    raise IntegrationPermissionError(
                        "Integration operation was denied",
                        provider_key=provider_key,
                        operation=operation,
                    )
                if 400 <= response.status_code < 500 and response.status_code != 429:
                    raise IntegrationValidationError(
                        "Integration request was rejected",
                        provider_key=provider_key,
                        operation=operation,
                    )
                last_error = httpx2.HTTPStatusError(
                    "Retryable integration response",
                    request=response.request,
                    response=response,
                )
            except (IntegrationAuthError, IntegrationPermissionError, IntegrationValidationError):
                raise
            except (TimeoutError, httpx2.RequestError) as exc:
                last_error = exc

            if attempt + 1 < settings.INTEGRATIONS_HTTP_RETRY_MAX_ATTEMPTS:
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
    }
    if last_status == 429:
        raise IntegrationRateLimitError("Integration rate limit exceeded", **context)
    if isinstance(last_error, (TimeoutError, httpx2.RequestError)):
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
