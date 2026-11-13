# apps/api/integrations/google_ads/client.py

"""Thin Google Ads REST client pinned to v26, verified 2026-11-13."""

from collections.abc import Awaitable, Callable
from typing import Any

import httpx2

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationDownloadTooLargeError,
    IntegrationError,
    IntegrationFailureDisposition,
    IntegrationPermissionError,
    IntegrationValidationError,
)
from services.integrations.http import (
    IntegrationRequestPolicy,
    consume_stream_with_retries,
    request_with_retries,
    resolve_before_dispatch,
)

GOOGLE_ADS_API_VERSION = "v26"
GOOGLE_ADS_HOST = "googleads.googleapis.com"
GOOGLE_ADS_API_BASE_URL = f"https://{GOOGLE_ADS_HOST}/{GOOGLE_ADS_API_VERSION}"
GOOGLE_ADS_UPLOAD_BASE_URL = f"https://{GOOGLE_ADS_HOST}/resumable/upload/{GOOGLE_ADS_API_VERSION}"
# Google serves the documents its API links to, such as invoice PDFs, from these domains.
_DOWNLOAD_DOMAINS = ("google.com", "googleapis.com")
_MAX_DOWNLOAD_REDIRECTS = 3
AccessTokenFn = Callable[[bool], Awaitable[str]]


class GoogleAdsRequestRejectedError(IntegrationValidationError):
    """A request Google refused, with Google's error so a caller can find the operations."""

    def __init__(self, message: str, *, failure: dict[str, Any], operation: str) -> None:
        super().__init__(
            message,
            provider_key="google_ads",
            operation=operation,
            failure_disposition=IntegrationFailureDisposition.REJECTED,
        )
        self.failure = failure


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
        params: dict[str, str] | None = None,
        max_response_bytes: int | None = None,
    ) -> Any:
        return await self._request(
            "GET",
            path,
            operation=operation,
            policy=policy,
            login_customer_id=login_customer_id,
            max_response_bytes=max_response_bytes,
            **({"params": params} if params else {}),
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

    async def download(self, url: str, *, operation: str, max_bytes: int) -> bytes:
        """Downloads a document Google Ads linked to, such as an invoice PDF.

        The address comes from Google's reply, so every hop is checked: the bearer token goes to
        Google's own hosts over HTTPS and nowhere else.

        Raises:
            IntegrationValidationError: When an address isn't on a Google host, or the redirects
                don't end.
            IntegrationDownloadTooLargeError: When the document is larger than `max_bytes`.
        """

        async def consume(response: httpx2.Response) -> tuple[str | None, bytes]:
            if response.is_redirect:
                return response.headers.get("Location"), b""
            body = bytearray()
            async for chunk in response.aiter_bytes():
                if len(body) + len(chunk) > max_bytes:
                    raise IntegrationDownloadTooLargeError(
                        "The document is too large to save.",
                        provider_key="google_ads",
                        operation=operation,
                    )
                body.extend(chunk)
            return None, bytes(body)

        target: httpx2.URL | None = _google_address(url)
        for _ in range(_MAX_DOWNLOAD_REDIRECTS + 1):
            if target is None:
                break
            location, body = await self._send_with_refresh(
                "GET",
                str(target),
                operation=operation,
                policy=IntegrationRequestPolicy.READ,
                login_customer_id=None,
                consume=consume,
                follow_redirects=False,
            )
            if location is None:
                return body
            target = _google_address(location, base=target)
        raise IntegrationValidationError(
            "Google Ads returned a document address that isn't on a Google host.",
            provider_key="google_ads",
            operation=operation,
            error_code="invalid_download_address",
            failure_disposition=IntegrationFailureDisposition.NOT_DISPATCHED,
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

    async def _send_with_refresh(self, method: str, url: str, **kwargs: Any) -> Any:
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
        consume: Callable[[httpx2.Response], Awaitable[Any]] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Sends one request, returning the reply or, with `consume`, what it reads from the
        stream."""
        headers = {
            **(extra_headers or {}),
            "Authorization": f"Bearer {token}",
        }
        if login_customer_id:
            headers["login-customer-id"] = normalize_customer_id(login_customer_id)

        request: dict[str, Any] = {
            "operation": operation,
            "provider_key": "google_ads",
            "client": self._client,
            "headers": headers,
            "validation_error_detail": lambda response: _google_ads_error_detail(
                response,
                operation=operation,
            ),
            "response_error_mapper": lambda response: _mapped_error(
                response,
                operation=operation,
            ),
            **kwargs,
        }
        try:
            if consume is not None:
                return await consume_stream_with_retries(
                    method,
                    url,
                    policy=policy,
                    consume=consume,
                    include_original_error=False,
                    **request,
                )
            return await request_with_retries(
                method, url, policy=policy, max_response_bytes=max_response_bytes, **request
            )
        except IntegrationError as exc:
            # httpx request objects retain headers; never carry the bearer
            # token beyond this provider boundary in exception context.
            exc.original_error = None
            raise


def _google_address(value: str, *, base: httpx2.URL | None = None) -> httpx2.URL | None:
    """Returns the address when it's HTTPS on one of Google's download domains."""
    try:
        url = base.join(value) if base is not None else httpx2.URL(value)
    except httpx2.InvalidURL:
        return None
    host = url.host.lower()
    on_google = any(host == name or host.endswith(f".{name}") for name in _DOWNLOAD_DOMAINS)
    return url if url.scheme == "https" and not url.port and on_google else None


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
    error = _error_object(response)
    if error is None:
        return fallback

    messages: list[str] = []
    for provider_error in provider_errors(error):
        normalized = _bounded_provider_message(provider_error.get("message"))
        if normalized and normalized not in messages:
            messages.append(normalized)
        if len(messages) == 3:
            break

    if not messages:
        fallback = _bounded_provider_message(error.get("message"))
        if fallback:
            messages.append(fallback)
    if not messages:
        return fallback

    return f"Google Ads rejected the {subject}: {' '.join(messages)}"[:1000]


def _mapped_error(response: httpx2.Response, *, operation: str) -> IntegrationError | None:
    error = _error_object(response)
    if error is None:
        return None
    if response.status_code == 403:
        return _unapproved_project_error(error, operation=operation)
    if response.status_code == 400:
        return GoogleAdsRequestRejectedError(
            _google_ads_error_detail(response, operation=operation),
            failure=error,
            operation=operation,
        )
    return None


def _unapproved_project_error(
    error: dict[str, Any],
    *,
    operation: str,
) -> IntegrationPermissionError | None:
    """Explain the v25+ refusal for a Cloud project that only has Test access."""
    if not any(
        isinstance(code := provider_error.get("errorCode"), dict)
        and code.get("authorizationError") == "CLOUD_PROJECT_NOT_APPROVED_FOR_PRODUCTION"
        for provider_error in provider_errors(error)
    ):
        return None
    return IntegrationPermissionError(
        "This Google Cloud project can only use Google Ads test accounts. In Google Cloud "
        "Console, open Google Ads API and apply for Explorer access.",
        provider_key="google_ads",
        operation=operation,
        error_code="cloud_project_not_approved",
        failure_disposition=IntegrationFailureDisposition.REJECTED,
    )


def _error_object(response: httpx2.Response) -> dict[str, Any] | None:
    """Returns Google's error, which `searchStream` wraps in a one-item array."""
    try:
        payload = response.json()
    except ValueError:
        return None
    if isinstance(payload, list) and payload:
        payload = payload[0]
    error = payload.get("error") if isinstance(payload, dict) else None
    return error if isinstance(error, dict) else None


def provider_errors(error: dict[str, Any]) -> list[dict[str, Any]]:
    """Returns each error Google lists inside one refusal."""
    details = error.get("details")
    if not isinstance(details, list):
        return []
    return [
        provider_error
        for detail in details
        if isinstance(detail, dict) and isinstance(detail.get("errors"), list)
        for provider_error in detail["errors"]
        if isinstance(provider_error, dict)
    ]


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
