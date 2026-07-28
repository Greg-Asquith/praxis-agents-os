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
        return await self._request("GET", path, operation=operation, params=params)

    async def post(
        self,
        path: str,
        *,
        operation: str,
        json: dict[str, Any],
        request_timeout: float | None = None,
    ) -> Any:
        kwargs: dict[str, Any] = {"json": json}
        if request_timeout is not None:
            kwargs["timeout"] = request_timeout
        return await self._request("POST", path, operation=operation, **kwargs)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        **kwargs: Any,
    ) -> Any:
        token = await self._access_token(False)
        try:
            response = await self._send(
                method,
                path,
                operation=operation,
                token=token,
                **kwargs,
            )
        except IntegrationAuthError:
            token = await self._access_token(True)
            response = await self._send(
                method,
                path,
                operation=operation,
                token=token,
                **kwargs,
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
        method: str,
        path: str,
        *,
        operation: str,
        token: str,
        **kwargs: Any,
    ) -> httpx2.Response:
        return await request_with_retries(
            method,
            f"{BIGQUERY_API_BASE_URL}/{path.lstrip('/')}",
            operation=operation,
            provider_key="bigquery",
            client=self._client,
            headers={"Authorization": f"Bearer {token}"},
            validation_error_detail=_bigquery_error_detail,
            **kwargs,
        )


def _bigquery_error_detail(response: httpx2.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return None
    errors = error.get("errors")
    if isinstance(errors, list):
        for item in errors:
            message = str(item.get("message", "")).strip() if isinstance(item, dict) else ""
            if message:
                return message
    message = str(error.get("message", "")).strip()
    return message or None
