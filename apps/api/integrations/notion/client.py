# apps/api/integrations/notion/client.py

"""Thin async Notion REST client over the shared integration HTTP seam."""

from collections.abc import Awaitable, Callable
from typing import Any

import httpx2

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationFailureDisposition,
    IntegrationValidationError,
)
from services.integrations.http import (
    IntegrationRequestPolicy,
    request_with_retries,
    resolve_before_dispatch,
)

NOTION_API_BASE_URL = "https://api.notion.com/v1"
NOTION_API_VERSION = "2026-03-11"
AccessTokenFn = Callable[[bool], Awaitable[str]]
ValidationErrorDetailFn = Callable[[httpx2.Response], str | None]


def fixed_access_token(access_token: str) -> AccessTokenFn:
    """Return a resolver that delegates forced refresh to the credential owner."""

    async def resolve(force: bool) -> str:
        if force:
            raise IntegrationAuthError(
                "Notion access token requires refresh",
                provider_key="notion",
                operation="refresh_access_token",
            )
        return access_token

    return resolve


class NotionClient:
    def __init__(
        self,
        access_token: AccessTokenFn,
        *,
        client: httpx2.AsyncClient | None = None,
        pacing_key: str | None = None,
    ) -> None:
        self._access_token = access_token
        self._client = client
        self._pacing_key = pacing_key

    async def get(
        self,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
    ) -> Any:
        return await self._request("GET", path, operation=operation, policy=policy)

    async def post(
        self,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        json: dict[str, Any],
        validation_error_detail: ValidationErrorDetailFn | None = None,
    ) -> Any:
        return await self._request(
            "POST",
            path,
            operation=operation,
            policy=policy,
            json=json,
            validation_error_detail=validation_error_detail,
        )

    async def patch(
        self,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        json: dict[str, Any],
        validation_error_detail: ValidationErrorDetailFn | None = None,
    ) -> Any:
        return await self._request(
            "PATCH",
            path,
            operation=operation,
            policy=policy,
            json=json,
            validation_error_detail=validation_error_detail,
        )

    async def _request(
        self,
        method: str,
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
                path,
                operation=operation,
                policy=policy,
                token=token,
                **kwargs,
            )
        content_type = response.headers.get("Content-Type", "").lower()
        if not content_type.startswith("application/json"):
            raise IntegrationValidationError(
                "Notion returned an unsupported response format",
                provider_key="notion",
                operation=operation,
                failure_disposition=(
                    IntegrationFailureDisposition.AMBIGUOUS
                    if policy is not IntegrationRequestPolicy.READ
                    else None
                ),
            )
        try:
            return response.json()
        except ValueError as exc:
            raise IntegrationValidationError(
                "Notion returned an invalid JSON response",
                provider_key="notion",
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
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        token: str,
        **kwargs: Any,
    ) -> httpx2.Response:
        if self._pacing_key is not None:
            from .pacing import acquire

            await acquire(self._pacing_key)
        return await request_with_retries(
            method,
            f"{NOTION_API_BASE_URL}/{path.lstrip('/')}",
            operation=operation,
            provider_key="notion",
            policy=policy,
            client=self._client,
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_API_VERSION,
            },
            **kwargs,
        )
