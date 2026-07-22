# apps/api/integrations/gmail/client.py

"""Thin async Gmail REST client over the shared integration HTTP seam."""

from collections.abc import Awaitable, Callable
from typing import Any

import httpx2

from core.exceptions.integration import IntegrationAuthError, IntegrationValidationError
from services.integrations.http import request_with_retries

GMAIL_API_BASE_URL = "https://gmail.googleapis.com/gmail/v1"
AccessTokenFn = Callable[[bool], Awaitable[str]]


class GmailClient:
    def __init__(
        self,
        access_token: AccessTokenFn,
        *,
        client: httpx2.AsyncClient | None = None,
    ) -> None:
        self._access_token = access_token
        self._client = client

    async def get(self, path: str, *, operation: str, params: dict[str, Any] | None = None) -> Any:
        return await self._request("GET", path, operation=operation, params=params)

    async def post(self, path: str, *, operation: str, json: dict[str, Any]) -> Any:
        return await self._request("POST", path, operation=operation, json=json)

    async def _request(self, method: str, path: str, *, operation: str, **kwargs: Any) -> Any:
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
                "Gmail returned an invalid JSON response",
                provider_key="gmail",
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
            f"{GMAIL_API_BASE_URL}/{path.lstrip('/')}",
            operation=operation,
            provider_key="gmail",
            client=self._client,
            headers={"Authorization": f"Bearer {token}"},
            **kwargs,
        )
