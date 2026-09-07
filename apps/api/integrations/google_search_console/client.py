# apps/api/integrations/google_search_console/client.py

"""Thin async Google Search Console REST client over the shared HTTP seam."""

from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx2

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationError,
    IntegrationFailureDisposition,
    IntegrationPermissionError,
    IntegrationValidationError,
)
from services.integrations.http import (
    IntegrationRequestPolicy,
    request_with_retries,
    resolve_before_dispatch,
)

GOOGLE_WEBMASTERS_BASE_URL = "https://www.googleapis.com/webmasters/v3"
GOOGLE_SEARCH_CONSOLE_BASE_URL = "https://searchconsole.googleapis.com/v1"
GOOGLE_INDEXING_BASE_URL = "https://indexing.googleapis.com/v3"
AccessTokenFn = Callable[[bool], Awaitable[str]]


class GoogleSearchConsoleClient:
    def __init__(
        self,
        access_token: AccessTokenFn,
        *,
        client: httpx2.AsyncClient | None = None,
    ) -> None:
        self._access_token = access_token
        self._client = client

    async def webmasters_get(
        self,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        params: dict[str, Any] | None = None,
        allow_empty: bool = False,
    ) -> Any:
        return await self._request(
            "GET",
            GOOGLE_WEBMASTERS_BASE_URL,
            path,
            operation=operation,
            policy=policy,
            params=params,
            allow_empty=allow_empty,
        )

    async def webmasters_post(
        self,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        json: dict[str, Any] | None = None,
        allow_empty: bool = False,
    ) -> Any:
        return await self._request(
            "POST",
            GOOGLE_WEBMASTERS_BASE_URL,
            path,
            operation=operation,
            policy=policy,
            json=json,
            allow_empty=allow_empty,
        )

    async def webmasters_put(
        self,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        json: dict[str, Any] | None = None,
        allow_empty: bool = False,
    ) -> Any:
        return await self._request(
            "PUT",
            GOOGLE_WEBMASTERS_BASE_URL,
            path,
            operation=operation,
            policy=policy,
            json=json,
            allow_empty=allow_empty,
        )

    async def inspection_post(
        self,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        json: dict[str, Any],
        allow_empty: bool = False,
    ) -> Any:
        return await self._request(
            "POST",
            GOOGLE_SEARCH_CONSOLE_BASE_URL,
            path,
            operation=operation,
            policy=policy,
            json=json,
            allow_empty=allow_empty,
        )

    async def indexing_get(
        self,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        params: dict[str, Any] | None = None,
        allow_empty: bool = False,
    ) -> Any:
        return await self._request(
            "GET",
            GOOGLE_INDEXING_BASE_URL,
            path,
            operation=operation,
            policy=policy,
            params=params,
            allow_empty=allow_empty,
        )

    async def indexing_post(
        self,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        json: dict[str, Any],
        allow_empty: bool = False,
    ) -> Any:
        return await self._request(
            "POST",
            GOOGLE_INDEXING_BASE_URL,
            path,
            operation=operation,
            policy=policy,
            json=json,
            allow_empty=allow_empty,
        )

    async def _request(
        self,
        method: str,
        base_url: str,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        allow_empty: bool,
        **kwargs: Any,
    ) -> Any:
        token = await resolve_before_dispatch(lambda: self._access_token(False))
        try:
            response = await self._send(
                method,
                base_url,
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
                base_url,
                path,
                operation=operation,
                policy=policy,
                token=token,
                **kwargs,
            )
        if allow_empty and not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise IntegrationValidationError(
                "Google Search Console returned an invalid JSON response",
                provider_key="google_search_console",
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
        base_url: str,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        token: str,
        **kwargs: Any,
    ) -> httpx2.Response:
        try:
            if self._client is None and base_url == GOOGLE_INDEXING_BASE_URL:

                async def reject_indexing_permission(response: httpx2.Response) -> None:
                    await response.aread()
                    _raise_indexing_permission_error(response, operation=operation)

                async with httpx2.AsyncClient(
                    event_hooks={"response": [reject_indexing_permission]}
                ) as client:
                    return await request_with_retries(
                        method,
                        f"{base_url}/{path.lstrip('/')}",
                        operation=operation,
                        provider_key="google_search_console",
                        policy=policy,
                        client=client,
                        headers={"Authorization": f"Bearer {token}"},
                        validation_error_detail=lambda response: _google_api_error_detail(
                            response,
                            operation=operation,
                        ),
                        **kwargs,
                    )
            return await request_with_retries(
                method,
                f"{base_url}/{path.lstrip('/')}",
                operation=operation,
                provider_key="google_search_console",
                policy=policy,
                client=self._client,
                headers={"Authorization": f"Bearer {token}"},
                validation_error_detail=lambda response: _google_api_error_detail(
                    response,
                    operation=operation,
                ),
                **kwargs,
            )
        except IntegrationError as exc:
            exc.original_error = None
            raise


def _google_api_error_detail(response: httpx2.Response, *, operation: str) -> str:
    fallback = "Google Search Console rejected the request."
    try:
        payload = response.json()
    except ValueError:
        return fallback
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return fallback
    messages: list[str] = []
    for value in (error.get("message"), error.get("status")):
        normalized = _bounded_provider_message(value)
        if normalized and normalized not in messages:
            messages.append(normalized)
    details = error.get("details")
    if isinstance(details, list):
        for detail in details:
            reason = detail.get("reason") if isinstance(detail, dict) else None
            normalized = _bounded_provider_message(reason)
            if normalized and normalized not in messages:
                messages.append(normalized)
            if len(messages) == 3:
                break
    if not messages:
        return fallback
    return f"Google Search Console rejected {operation}: {' '.join(messages)}"[:1000]


def _raise_indexing_permission_error(response: httpx2.Response, *, operation: str) -> None:
    if response.status_code != 403:
        return
    raise IntegrationPermissionError(
        _google_indexing_permission_detail(response, operation=operation),
        provider_key="google_search_console",
        operation=operation,
        failure_disposition=IntegrationFailureDisposition.REJECTED,
    )


def _google_indexing_permission_detail(response: httpx2.Response, *, operation: str) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    error = payload.get("error") if isinstance(payload, dict) else None
    details = error.get("details") if isinstance(error, dict) else None
    if isinstance(details, list):
        for detail in details:
            reason = detail.get("reason") if isinstance(detail, dict) else None
            normalized = _bounded_provider_message(reason)
            if normalized:
                return f"Google Search Console rejected {operation}: {normalized}"[:1_000]
    return _google_api_error_detail(response, operation=operation)


def _bounded_provider_message(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized[:800] or None


def normalize_site_url(value: str) -> str:
    normalized = value.strip()
    if normalized.startswith("sc-domain:"):
        domain = normalized.removeprefix("sc-domain:").strip().lower()
        if not domain or "/" in domain or ":" in domain:
            raise _invalid_site_url()
        return f"sc-domain:{domain}"

    parsed = urlsplit(normalized)
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise _invalid_site_url()
    if not normalized.endswith("/") or parsed.query or parsed.fragment:
        raise _invalid_site_url()
    hostname = parsed.hostname
    if not hostname:
        raise _invalid_site_url()
    host = hostname.lower()
    try:
        port = parsed.port
    except ValueError as exc:
        raise _invalid_site_url() from exc
    if port is not None:
        host = f"{host}:{port}"
    return urlunsplit((parsed.scheme.lower(), host, parsed.path, "", ""))


def site_path(site_url: str) -> str:
    return f"sites/{quote(normalize_site_url(site_url), safe='')}"


def _invalid_site_url() -> IntegrationValidationError:
    return IntegrationValidationError(
        "Google Search Console site URL must be a domain property or a URL prefix ending in '/'",
        provider_key="google_search_console",
        operation="normalize_site_url",
    )
