# apps/api/integrations/google_ads/client.py

"""Thin Google Ads REST client pinned to v24, verified 2026-07-22."""

from collections.abc import Awaitable, Callable
from typing import Any

import httpx2
from pydantic import SecretStr

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

GOOGLE_ADS_API_VERSION = "v24"
GOOGLE_ADS_API_BASE_URL = f"https://googleads.googleapis.com/{GOOGLE_ADS_API_VERSION}"
AccessTokenFn = Callable[[bool], Awaitable[str]]


class GoogleAdsClient:
    def __init__(
        self,
        access_token: AccessTokenFn,
        *,
        developer_token: SecretStr,
        client: httpx2.AsyncClient | None = None,
    ) -> None:
        self._access_token = access_token
        self._developer_token = developer_token
        self._client = client

    async def get(
        self,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        login_customer_id: str | None = None,
    ) -> Any:
        return await self._request(
            "GET",
            path,
            operation=operation,
            policy=policy,
            login_customer_id=login_customer_id,
        )

    async def post(
        self,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        json: dict[str, Any],
        login_customer_id: str | None = None,
    ) -> Any:
        return await self._request(
            "POST",
            path,
            operation=operation,
            policy=policy,
            login_customer_id=login_customer_id,
            json=json,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        login_customer_id: str | None,
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
                login_customer_id=login_customer_id,
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
                login_customer_id=login_customer_id,
                **kwargs,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise IntegrationValidationError(
                "Google Ads returned an invalid JSON response",
                provider_key="google_ads",
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
        login_customer_id: str | None,
        **kwargs: Any,
    ) -> httpx2.Response:
        headers = {
            "Authorization": f"Bearer {token}",
            "developer-token": self._developer_token.get_secret_value(),
        }
        if login_customer_id:
            headers["login-customer-id"] = normalize_customer_id(login_customer_id)
        try:
            return await request_with_retries(
                method,
                f"{GOOGLE_ADS_API_BASE_URL}/{path.lstrip('/')}",
                operation=operation,
                provider_key="google_ads",
                policy=policy,
                client=self._client,
                headers=headers,
                **kwargs,
            )
        except IntegrationError as exc:
            # httpx request objects retain headers; never carry the developer
            # token beyond this provider boundary in exception context.
            exc.original_error = None
            raise


def normalize_customer_id(value: str) -> str:
    normalized = "".join(character for character in value if character.isdigit())
    if not normalized:
        raise IntegrationValidationError(
            "Google Ads customer id is invalid",
            provider_key="google_ads",
            operation="normalize_customer_id",
        )
    return normalized
