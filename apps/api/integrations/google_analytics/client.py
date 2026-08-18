# apps/api/integrations/google_analytics/client.py

"""Thin async Google Analytics REST client over the shared HTTP seam."""

from collections.abc import Awaitable, Callable
from typing import Any

import httpx2

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationError,
    IntegrationFailureDisposition,
    IntegrationValidationError,
)
from services.integrations.http import (
    IntegrationRequestPolicy,
    request_with_retries,
    resolve_before_dispatch,
)

GOOGLE_ANALYTICS_DATA_BASE_URL = "https://analyticsdata.googleapis.com/v1beta"
GOOGLE_ANALYTICS_ADMIN_BASE_URL = "https://analyticsadmin.googleapis.com/v1beta"
AccessTokenFn = Callable[[bool], Awaitable[str]]


class GoogleAnalyticsClient:
    def __init__(
        self,
        access_token: AccessTokenFn,
        *,
        client: httpx2.AsyncClient | None = None,
    ) -> None:
        self._access_token = access_token
        self._client = client

    async def data_get(
        self,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        params: dict[str, Any] | None = None,
    ) -> Any:
        return await self._request(
            "GET",
            GOOGLE_ANALYTICS_DATA_BASE_URL,
            path,
            operation=operation,
            policy=policy,
            params=params,
        )

    async def data_post(
        self,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        json: dict[str, Any],
    ) -> Any:
        return await self._request(
            "POST",
            GOOGLE_ANALYTICS_DATA_BASE_URL,
            path,
            operation=operation,
            policy=policy,
            json=json,
        )

    async def admin_get(
        self,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        params: dict[str, Any] | None = None,
    ) -> Any:
        return await self._request(
            "GET",
            GOOGLE_ANALYTICS_ADMIN_BASE_URL,
            path,
            operation=operation,
            policy=policy,
            params=params,
        )

    async def admin_get_paged(
        self,
        path: str,
        *,
        items_key: str,
        page_size: int,
        max_pages: int,
    ) -> tuple[dict[str, Any], ...]:
        if page_size < 1 or max_pages < 1:
            raise ValueError("page_size and max_pages must be positive")
        items: list[dict[str, Any]] = []
        page_token: str | None = None
        seen_tokens: set[str] = set()
        for _page in range(max_pages):
            params: dict[str, Any] = {"pageSize": page_size}
            if page_token is not None:
                params["pageToken"] = page_token
            payload = await self.admin_get(
                path,
                operation=f"list_{items_key}",
                policy=IntegrationRequestPolicy.READ,
                params=params,
            )
            if not isinstance(payload, dict):
                raise _invalid_page(items_key)
            page_items = payload.get(items_key, [])
            if not isinstance(page_items, list):
                raise _invalid_page(items_key)
            items.extend(item for item in page_items if isinstance(item, dict))
            next_token = str(payload.get("nextPageToken", "")).strip()
            if not next_token:
                return tuple(items)
            if next_token in seen_tokens:
                raise IntegrationValidationError(
                    "Google Analytics repeated a discovery page token; retry discovery",
                    provider_key="google_analytics",
                    operation=f"list_{items_key}",
                )
            seen_tokens.add(next_token)
            page_token = next_token
        raise IntegrationValidationError(
            "Google Analytics property discovery exceeded its page limit",
            provider_key="google_analytics",
            operation=f"list_{items_key}",
        )

    async def _request(
        self,
        method: str,
        base_url: str,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        **kwargs: Any,
    ) -> Any:
        token = await resolve_before_dispatch(lambda: self._access_token(False))
        try:
            response = await self._send(
                method,
                base_url,
                path,
                operation=operation,
                policy=policy,
                token=token,
                **kwargs,
            )
        except IntegrationAuthError:
            token = await resolve_before_dispatch(lambda: self._access_token(True))
            response = await self._send(
                method,
                base_url,
                path,
                operation=operation,
                policy=policy,
                token=token,
                **kwargs,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise IntegrationValidationError(
                "Google Analytics returned an invalid JSON response",
                provider_key="google_analytics",
                operation=operation,
                original_error=exc,
                failure_disposition=(
                    IntegrationFailureDisposition.AMBIGUOUS
                    if policy is not IntegrationRequestPolicy.READ
                    else None
                ),
            ) from exc

    async def _send(
        self,
        method: str,
        base_url: str,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        token: str,
        **kwargs: Any,
    ) -> httpx2.Response:
        try:
            return await request_with_retries(
                method,
                f"{base_url}/{path.lstrip('/')}",
                operation=operation,
                provider_key="google_analytics",
                policy=policy,
                client=self._client,
                headers={"Authorization": f"Bearer {token}"},
                validation_error_detail=lambda response: _google_api_error_detail(
                    response,
                    operation=operation,
                ),
                **kwargs,
            )
        except IntegrationError as exc:
            exc.original_error = None
            raise


def _invalid_page(items_key: str) -> IntegrationValidationError:
    return IntegrationValidationError(
        f"Google Analytics returned an invalid {items_key} page",
        provider_key="google_analytics",
        operation=f"list_{items_key}",
    )


def _google_api_error_detail(response: httpx2.Response, *, operation: str) -> str:
    fallback = "Google Analytics rejected the request."
    try:
        payload = response.json()
    except ValueError:
        return fallback
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return fallback
    messages: list[str] = []
    for value in (error.get("message"), error.get("status")):
        normalized = _bounded_provider_message(value)
        if normalized and normalized not in messages:
            messages.append(normalized)
    details = error.get("details")
    if isinstance(details, list):
        for detail in details:
            reason = detail.get("reason") if isinstance(detail, dict) else None
            normalized = _bounded_provider_message(reason)
            if normalized and normalized not in messages:
                messages.append(normalized)
            if len(messages) == 3:
                break
    if not messages:
        return fallback
    return f"Google Analytics rejected {operation}: {' '.join(messages)}"[:1000]


def _bounded_provider_message(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized[:800] or None


def normalize_property_id(value: str) -> str:
    normalized = value.strip()
    if normalized.startswith("properties/"):
        normalized = normalized.removeprefix("properties/")
    if not normalized.isdigit():
        raise IntegrationValidationError(
            "Google Analytics property id must contain digits only",
            provider_key="google_analytics",
            operation="normalize_property_id",
        )
    return normalized
