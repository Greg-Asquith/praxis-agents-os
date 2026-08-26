# apps/api/integrations/notion/client.py

"""Thin async Notion REST client over the shared integration HTTP seam."""

from collections.abc import Awaitable, Callable
from typing import Any

import httpx2

from core.exceptions.integration import IntegrationAuthError, IntegrationValidationError
from services.integrations.http import (
    IntegrationRequestPolicy,
    request_with_retries,
    resolve_before_dispatch,
)

NOTION_API_BASE_URL = "https://api.notion.com/v1"
NOTION_API_VERSION = "2026-03-11"
AccessTokenFn = Callable[[bool], Awaitable[str]]


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
    ) -> None:
        self._access_token = access_token
        self._client = client

    async def get(
        self,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
    ) -> Any:
        token = await resolve_before_dispatch(lambda: self._access_token(False))
        try:
            response = await self._send(path, operation=operation, policy=policy, token=token)
        except IntegrationAuthError:
            token = await resolve_before_dispatch(lambda: self._access_token(True))
            response = await self._send(path, operation=operation, policy=policy, token=token)
        try:
            return response.json()
        except ValueError as exc:
            raise IntegrationValidationError(
                "Notion returned an invalid JSON response",
                provider_key="notion",
                operation=operation,
                original_error=exc,
            ) from exc

    async def _send(
        self,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        token: str,
    ) -> httpx2.Response:
        return await request_with_retries(
            "GET",
            f"{NOTION_API_BASE_URL}/{path.lstrip('/')}",
            operation=operation,
            provider_key="notion",
            policy=policy,
            client=self._client,
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_API_VERSION,
            },
        )
