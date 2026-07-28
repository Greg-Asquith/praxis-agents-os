# apps/api/integrations/bigquery/client.py

"""Thin async BigQuery REST client over the shared integration HTTP seam."""

from collections.abc import Awaitable, Callable
from typing import Any

import httpx2

from core.exceptions.integration import IntegrationAuthError, IntegrationValidationError
from services.integrations.http import request_with_retries

BIGQUERY_API_BASE_URL = "https://bigquery.googleapis.com/bigquery/v2"
AccessTokenFn = Callable[[bool], Awaitable[str]]


class BigQueryClient:
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
        token = await self._access_token(False)
        try:
            response = await self._send(
                path,
                operation=operation,
                token=token,
                params=params,
            )
        except IntegrationAuthError:
            token = await self._access_token(True)
            response = await self._send(
                path,
                operation=operation,
                token=token,
                params=params,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise IntegrationValidationError(
                "BigQuery returned an invalid JSON response",
                provider_key="bigquery",
                operation=operation,
                original_error=exc,
            ) from exc

    async def _send(
        self,
        path: str,
        *,
        operation: str,
        token: str,
        params: dict[str, Any] | None,
    ) -> httpx2.Response:
        return await request_with_retries(
            "GET",
            f"{BIGQUERY_API_BASE_URL}/{path.lstrip('/')}",
            operation=operation,
            provider_key="bigquery",
            client=self._client,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        )
