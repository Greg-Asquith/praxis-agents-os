# apps/api/integrations/airtable/client.py

"""Thin async Airtable REST client over the shared integration HTTP seam."""

from collections.abc import Awaitable, Callable
from typing import Any

import httpx2

from core.exceptions.integration import IntegrationValidationError
from services.integrations.http import request_with_retries

AIRTABLE_API_BASE_URL = "https://api.airtable.com/v0"
AccessTokenFn = Callable[[], Awaitable[str]]


class AirtableClient:
    def __init__(
        self,
        access_token: AccessTokenFn,
        *,
        client: httpx2.AsyncClient | None = None,
    ) -> None:
        self._access_token = access_token
        self._client = client

    async def get(
        self,
        path: str,
        *,
        operation: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        return await self._request("GET", path, operation=operation, params=params)

    async def post(self, path: str, *, operation: str, json: dict[str, Any]) -> Any:
        return await self._request("POST", path, operation=operation, json=json)

    async def patch(self, path: str, *, operation: str, json: dict[str, Any]) -> Any:
        return await self._request("PATCH", path, operation=operation, json=json)

    async def _request(self, method: str, path: str, *, operation: str, **kwargs: Any) -> Any:
        token = await self._access_token()
        response = await request_with_retries(
            method,
            f"{AIRTABLE_API_BASE_URL}/{path.lstrip('/')}",
            operation=operation,
            provider_key="airtable",
            client=self._client,
            headers={"Authorization": f"Bearer {token}"},
            **kwargs,
        )
        try:
            return response.json()
        except ValueError as exc:
            raise IntegrationValidationError(
                "Airtable returned an invalid JSON response",
                provider_key="airtable",
                operation=operation,
                original_error=exc,
            ) from exc
