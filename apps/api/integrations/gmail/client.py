# apps/api/integrations/gmail/client.py

"""Thin async Gmail REST client over the shared integration HTTP seam."""

from collections.abc import Awaitable, Callable
from typing import Any

import httpx2

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationError,
    IntegrationFailureDisposition,
    IntegrationRateLimitError,
    IntegrationSendingLimitError,
    IntegrationValidationError,
)
from services.integrations.http import (
    IntegrationRequestPolicy,
    request_with_retries,
    resolve_before_dispatch,
    retry_after_seconds,
)

GMAIL_API_BASE_URL = "https://gmail.googleapis.com/gmail/v1"
AccessTokenFn = Callable[[bool], Awaitable[str]]

_THROTTLE_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded"})


def gmail_send_error(response: httpx2.Response, *, operation: str) -> IntegrationError | None:
    """Maps Gmail's throttling and sending-limit responses for senders that pace themselves.

    Gmail rejected the request in each case, so nothing was sent. Other responses keep the
    shared mapping.
    """
    status = response.status_code
    if status not in {403, 429}:
        return None
    error = _error_body(response)
    reasons = {item.get("reason") for item in error.get("errors") or () if isinstance(item, dict)}
    message = str(error.get("message") or "")
    context = {
        "provider_key": "gmail",
        "operation": operation,
        "failure_disposition": IntegrationFailureDisposition.REJECTED,
    }
    if status == 429 and "(Mail sending)" in message:
        return IntegrationSendingLimitError(
            "The mailbox reached Gmail's daily sending limit", error_code="daily_limit", **context
        )
    if status == 403 and "dailyLimitExceeded" in reasons:
        # The Cloud project's API quota, shared by every mailbox, not this mailbox's limit.
        return IntegrationRateLimitError(
            "Praxis reached its daily Gmail API quota", error_code="platform_quota", **context
        )
    if status == 429 or reasons & _THROTTLE_REASONS:
        return IntegrationRateLimitError(
            "Gmail asked Praxis to slow down",
            retry_after_seconds=retry_after_seconds(response),
            **context,
        )
    return None


def _error_body(response: httpx2.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    error = payload.get("error") if isinstance(payload, dict) else None
    return error if isinstance(error, dict) else {}


class GmailClient:
    def __init__(
        self,
        access_token: AccessTokenFn,
        *,
        client: httpx2.AsyncClient | None = None,
        send_errors: bool = False,
    ) -> None:
        self._access_token = access_token
        self._client = client
        # Only senders that pace themselves opt in; other tools keep the shared mapping.
        self._send_errors = send_errors

    async def get(
        self,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        params: dict[str, Any] | None = None,
    ) -> Any:
        return await self._request("GET", path, operation=operation, policy=policy, params=params)

    async def post(
        self,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        json: dict[str, Any],
    ) -> Any:
        return await self._request("POST", path, operation=operation, policy=policy, json=json)

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
        try:
            return response.json()
        except ValueError as exc:
            raise IntegrationValidationError(
                "Gmail returned an invalid JSON response",
                provider_key="gmail",
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
        return await request_with_retries(
            method,
            f"{GMAIL_API_BASE_URL}/{path.lstrip('/')}",
            operation=operation,
            provider_key="gmail",
            policy=policy,
            client=self._client,
            response_error_mapper=(
                (lambda response: gmail_send_error(response, operation=operation))
                if self._send_errors
                else None
            ),
            headers={"Authorization": f"Bearer {token}"},
            **kwargs,
        )
