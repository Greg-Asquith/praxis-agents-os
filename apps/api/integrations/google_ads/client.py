# apps/api/integrations/google_ads/client.py

"""Thin Google Ads REST client pinned to v26, verified 2026-11-13."""

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

GOOGLE_ADS_API_VERSION = "v26"
GOOGLE_ADS_HOST = "googleads.googleapis.com"
GOOGLE_ADS_API_BASE_URL = f"https://{GOOGLE_ADS_HOST}/{GOOGLE_ADS_API_VERSION}"
GOOGLE_ADS_UPLOAD_BASE_URL = f"https://{GOOGLE_ADS_HOST}/resumable/upload/{GOOGLE_ADS_API_VERSION}"
AccessTokenFn = Callable[[bool], Awaitable[str]]


class GoogleAdsClient:
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
        login_customer_id: str | None = None,
        max_response_bytes: int | None = None,
    ) -> Any:
        return await self._request(
            "GET",
            path,
            operation=operation,
            policy=policy,
            login_customer_id=login_customer_id,
            max_response_bytes=max_response_bytes,
        )

    async def post(
        self,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        json: dict[str, Any],
        login_customer_id: str | None = None,
        max_response_bytes: int | None = None,
    ) -> Any:
        return await self._request(
            "POST",
            path,
            operation=operation,
            policy=policy,
            login_customer_id=login_customer_id,
            json=json,
            max_response_bytes=max_response_bytes,
        )

    async def upload_request(
        self,
        method: str,
        url: str,
        *,
        operation: str,
        headers: dict[str, str],
        login_customer_id: str | None = None,
        **kwargs: Any,
    ) -> httpx2.Response:
        """Sends one resumable upload request once, and only to Google Ads' own host.

        Upload addresses come from Google's reply headers, so the bearer token is never sent
        anywhere else. The caller reads the reply's headers and resumes after an unclear reply.
        """
        parsed = httpx2.URL(url)
        if parsed.scheme != "https" or parsed.host != GOOGLE_ADS_HOST or parsed.port:
            raise IntegrationValidationError(
                "Google Ads returned an upload address that isn't on its own host.",
                provider_key="google_ads",
                operation=operation,
                error_code="invalid_upload_address",
                failure_disposition=IntegrationFailureDisposition.NOT_DISPATCHED,
            )
        return await self._send_with_refresh(
            method,
            url,
            operation=operation,
            policy=IntegrationRequestPolicy.MUTATION,
            login_customer_id=login_customer_id,
            extra_headers=headers,
            follow_redirects=False,
            **kwargs,
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
        response = await self._send_with_refresh(
            method,
            f"{GOOGLE_ADS_API_BASE_URL}/{path.lstrip('/')}",
            operation=operation,
            policy=policy,
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

    async def _send_with_refresh(self, method: str, url: str, **kwargs: Any) -> httpx2.Response:
        token = await resolve_before_dispatch(lambda: self._access_token(False))
        try:
            return await self._send(method, url, token=token, **kwargs)
        except IntegrationAuthError:
            token = await resolve_before_dispatch(lambda: self._access_token(True))
            return await self._send(method, url, token=token, **kwargs)

    async def _send(
        self,
        method: str,
        url: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        token: str,
        login_customer_id: str | None,
        max_response_bytes: int | None = None,
        extra_headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx2.Response:
        headers = {
            **(extra_headers or {}),
            "Authorization": f"Bearer {token}",
        }
        if login_customer_id:
            headers["login-customer-id"] = normalize_customer_id(login_customer_id)

        try:
            return await request_with_retries(
                method,
                url,
                operation=operation,
                provider_key="google_ads",
                policy=policy,
                max_response_bytes=max_response_bytes,
                client=self._client,
                headers=headers,
                validation_error_detail=lambda response: _google_ads_error_detail(
                    response,
                    operation=operation,
                ),
                **kwargs,
            )
        except IntegrationError as exc:
            # httpx request objects retain headers; never carry the developer
            # token beyond this provider boundary in exception context.
            exc.original_error = None
            raise


def _google_ads_error_detail(
    response: httpx2.Response,
    *,
    operation: str,
) -> str:
    """Extract a bounded, actionable message from a Google Ads error response."""
    subject = "query" if operation == "run_report" else "request"
    fallback = (
        "Google Ads rejected the query. Check that its fields and filters are valid GAQL."
        if operation == "run_report"
        else "Google Ads rejected the request."
    )
    try:
        payload = response.json()
    except ValueError:
        return fallback
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return fallback

    messages: list[str] = []
    details = error.get("details")
    if isinstance(details, list):
        for detail in details:
            provider_errors = detail.get("errors") if isinstance(detail, dict) else None
            if not isinstance(provider_errors, list):
                continue
            for provider_error in provider_errors:
                message = (
                    provider_error.get("message") if isinstance(provider_error, dict) else None
                )
                normalized = _bounded_provider_message(message)
                if normalized and normalized not in messages:
                    messages.append(normalized)
                if len(messages) == 3:
                    break
            if len(messages) == 3:
                break

    if not messages:
        fallback = _bounded_provider_message(error.get("message"))
        if fallback:
            messages.append(fallback)
    if not messages:
        return fallback

    return f"Google Ads rejected the {subject}: {' '.join(messages)}"[:1000]


def _bounded_provider_message(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized[:800] or None


def normalize_customer_id(value: str) -> str:
    normalized = "".join(character for character in value if character.isdigit())
    if not normalized:
        raise IntegrationValidationError(
            "Google Ads customer id is invalid",
            provider_key="google_ads",
            operation="normalize_customer_id",
        )
    return normalized
