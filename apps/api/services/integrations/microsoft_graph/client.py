# apps/api/services/integrations/microsoft_graph/client.py

"""Thin async client for the global Microsoft Graph API."""

import asyncio
import ipaddress
import logging
import socket
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx2

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationFailureDisposition,
    IntegrationValidationError,
)
from core.settings import settings
from services.integrations.http import (
    IntegrationRequestPolicy,
    consume_stream_with_retries,
    request_with_retries,
    resolve_before_dispatch,
)

from .errors import graph_response_error
from .pacing import paced_request

GRAPH_API_BASE_URL = "https://graph.microsoft.com/v1.0"
AccessTokenFn = Callable[[bool], Awaitable[str]]

logger = logging.getLogger(__name__)

_OUTLOOK_PATH_PREFIXES = (
    "/me/messages",
    "/me/mailFolders",
    "/me/events",
    "/me/calendars",
    "/me/calendarView",
    "/users/",
    "/subscriptions",
)


async def _resolve_host(host: str, port: int) -> tuple[str, ...]:
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        try:
            records = await asyncio.get_running_loop().getaddrinfo(
                host,
                port,
                type=socket.SOCK_STREAM,
            )
        except OSError:
            return ()
        return tuple(dict.fromkeys(record[4][0] for record in records))
    return (literal.compressed,)


def fixed_access_token(access_token: str) -> AccessTokenFn:
    """Return an access-token resolver that cannot refresh its credential."""

    async def resolve(force: bool) -> str:
        if force:
            raise IntegrationAuthError(
                "Microsoft Graph access token requires refresh",
                provider_key="microsoft_graph",
                operation="refresh_access_token",
            )
        return access_token

    return resolve


class MicrosoftGraphClient:
    """Issue paced Graph requests with stable headers and typed failures."""

    def __init__(
        self,
        access_token: AccessTokenFn,
        *,
        provider_key: str,
        client: httpx2.AsyncClient | None = None,
        pacing_key: str | None = None,
    ) -> None:
        self._access_token = access_token
        self._provider_key = provider_key
        self._client = client
        self._pacing_key = pacing_key

    async def get(
        self,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        return await self._request(
            "GET", path, operation=operation, policy=policy, params=params, headers=headers
        )

    async def post(
        self,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        return await self._request(
            "POST",
            path,
            operation=operation,
            policy=policy,
            json=json,
            params=params,
            headers=headers,
        )

    async def patch(
        self,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        return await self._request(
            "PATCH",
            path,
            operation=operation,
            policy=policy,
            json=json,
            params=params,
            headers=headers,
        )

    async def delete(
        self,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        return await self._request(
            "DELETE", path, operation=operation, policy=policy, params=params, headers=headers
        )

    async def paginate(
        self,
        path: str,
        *,
        operation: str,
        params: dict[str, Any] | None,
        max_items: int,
        max_pages: int,
    ) -> list[dict[str, Any]]:
        """Follow bounded Graph pagination while treating next links as opaque URLs."""
        if max_items < 1 or max_pages < 1:
            raise ValueError("Microsoft Graph pagination bounds must be positive")
        items: list[dict[str, Any]] = []
        next_path: str | None = path
        next_params = params
        for _ in range(max_pages):
            if next_path is None or len(items) >= max_items:
                break
            payload = await self.get(
                next_path,
                operation=operation,
                policy=IntegrationRequestPolicy.READ,
                params=next_params,
            )
            if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
                raise self._response_error(operation)
            items.extend(value for value in payload["value"] if isinstance(value, dict))
            raw_next = payload.get("@odata.nextLink")
            next_path = raw_next if isinstance(raw_next, str) and raw_next else None
            next_params = None
        return items[:max_items]

    async def get_bytes(self, url: str, *, operation: str, max_bytes: int) -> bytes:
        """Read a bounded pre-authenticated download URL without bearer credentials."""
        if max_bytes < 1:
            raise ValueError("Microsoft Graph byte limit must be positive")
        pinned_url, original_host = await self._public_download_target(url, operation=operation)
        if self._client is not None:
            return await self._get_bytes_with_client(
                self._client,
                url=pinned_url,
                original_host=original_host,
                operation=operation,
                max_bytes=max_bytes,
            )
        async with httpx2.AsyncClient() as client:
            return await self._get_bytes_with_client(
                client,
                url=pinned_url,
                original_host=original_host,
                operation=operation,
                max_bytes=max_bytes,
            )

    async def get_graph_bytes(self, path: str, *, operation: str, max_bytes: int) -> bytes:
        """Reads bounded binary content from Graph with one credential refresh."""
        if max_bytes < 1:
            raise ValueError("Microsoft Graph byte limit must be positive")
        url = self._graph_url(path)
        request_headers = self._request_headers(path, None)
        request_headers["Accept"] = "*/*"

        async def consume(response: httpx2.Response) -> bytes:
            if response.status_code != 200:
                raise self._response_error(operation)
            return await self._consume_bytes(response, operation=operation, max_bytes=max_bytes)

        async def download(token: str) -> bytes:
            request_headers["Authorization"] = f"Bearer {token}"
            return await consume_stream_with_retries(
                "GET",
                url,
                operation=operation,
                provider_key=self._provider_key,
                policy=IntegrationRequestPolicy.READ,
                consume=consume,
                client=self._client,
                attempt_context=lambda: self._request_attempt(request_headers),
                include_original_error=False,
                headers=request_headers,
                follow_redirects=False,
            )

        token = await resolve_before_dispatch(lambda: self._access_token(False))
        try:
            return await download(token)
        except IntegrationAuthError:
            token = await resolve_before_dispatch(lambda: self._access_token(True))
            return await download(token)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        headers: dict[str, str] | None = None,
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
                headers=headers,
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
                headers=headers,
                **kwargs,
            )
        if response.status_code in {202, 204} and not response.content:
            return None
        if not response.headers.get("Content-Type", "").lower().startswith("application/json"):
            raise self._response_error(operation, policy=policy)
        try:
            return response.json()
        except ValueError as exc:
            raise self._response_error(operation, policy=policy, original_error=exc) from exc

    async def _send(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        policy: IntegrationRequestPolicy,
        token: str,
        headers: dict[str, str] | None,
        **kwargs: Any,
    ) -> httpx2.Response:
        request_headers = self._request_headers(path, headers)
        request_headers["Authorization"] = f"Bearer {token}"
        response = await request_with_retries(
            method,
            self._graph_url(path),
            operation=operation,
            provider_key=self._provider_key,
            policy=policy,
            client=self._client,
            response_error_mapper=lambda value: graph_response_error(
                value,
                provider_key=self._provider_key,
                operation=operation,
            ),
            attempt_context=lambda: self._request_attempt(request_headers),
            headers=request_headers,
            **kwargs,
        )
        request_id = response.headers.get("request-id")
        if request_id:
            logger.debug("Microsoft Graph request completed", extra={"request_id": request_id})
        return response

    async def _get_bytes_with_client(
        self,
        client: httpx2.AsyncClient,
        *,
        url: httpx2.URL,
        original_host: str,
        operation: str,
        max_bytes: int,
    ) -> bytes:
        download_headers = {
            "Accept": "*/*",
            "Host": self._host_header(url, original_host),
            "User-Agent": self._user_agent(),
        }

        async def consume(response: httpx2.Response) -> bytes:
            return await self._consume_bytes(response, operation=operation, max_bytes=max_bytes)

        return await consume_stream_with_retries(
            "GET",
            url,
            operation=operation,
            provider_key=self._provider_key,
            policy=IntegrationRequestPolicy.READ,
            consume=consume,
            client=client,
            attempt_context=lambda: self._request_attempt(download_headers),
            include_original_error=False,
            headers=download_headers,
            extensions={"sni_hostname": original_host},
            follow_redirects=False,
            timeout=settings.INTEGRATIONS_HTTP_TIMEOUT_SECONDS,
        )

    async def _consume_bytes(
        self, response: httpx2.Response, *, operation: str, max_bytes: int
    ) -> bytes:
        content_length = response.headers.get("Content-Length")
        if content_length and content_length.isdigit() and int(content_length) > max_bytes:
            raise self._size_error(operation)
        body = bytearray()
        async for chunk in response.aiter_bytes():
            if len(body) + len(chunk) > max_bytes:
                raise self._size_error(operation)
            body.extend(chunk)
        return bytes(body)

    @asynccontextmanager
    async def _request_attempt(
        self,
        headers: httpx2.Headers | dict[str, str],
    ) -> AsyncIterator[None]:
        headers["client-request-id"] = str(uuid4())
        async with paced_request(self._pacing_key or ""):
            yield

    def _request_headers(
        self,
        path: str,
        headers: dict[str, str] | None,
    ) -> httpx2.Headers:
        values = httpx2.Headers(headers)
        values["Accept"] = "application/json"
        values["User-Agent"] = self._user_agent()
        if self._uses_immutable_ids(path):
            prefer = values.get("Prefer")
            immutable = 'IdType="ImmutableId"'
            values["Prefer"] = f"{prefer}, {immutable}" if prefer else immutable
        return values

    async def _public_download_target(
        self,
        url: str,
        *,
        operation: str,
    ) -> tuple[httpx2.URL, str]:
        try:
            parsed = httpx2.URL(url)
        except Exception:
            raise self._download_url_error(operation) from None
        if parsed.scheme != "https" or not parsed.host or parsed.username or parsed.password:
            raise self._download_url_error(operation)
        port = parsed.port or 443
        addresses = await _resolve_host(parsed.host, port)
        if not addresses:
            raise self._download_url_error(operation)
        try:
            public_addresses = tuple(
                ipaddress.ip_address(address).compressed
                for address in addresses
                if ipaddress.ip_address(address).is_global
            )
        except ValueError:
            raise self._download_url_error(operation) from None
        if len(public_addresses) != len(addresses):
            raise self._download_url_error(operation)
        return parsed.copy_with(host=public_addresses[0]), parsed.host

    def _host_header(self, url: httpx2.URL, original_host: str) -> str:
        host = original_host
        try:
            if ipaddress.ip_address(host).version == 6:
                host = f"[{host}]"
        except ValueError:
            pass
        return host if url.port in {None, 443} else f"{host}:{url.port}"

    def _user_agent(self) -> str:
        return f"ISV|Praxis|PraxisAgents-{self._provider_key}/{settings.APP_VERSION}"

    def _graph_url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            parsed = urlparse(path)
            if parsed.scheme != "https" or parsed.netloc.casefold() != "graph.microsoft.com":
                raise ValueError("Microsoft Graph pagination URL must use the global Graph host")
            return path
        return f"{GRAPH_API_BASE_URL}/{path.lstrip('/')}"

    def _uses_immutable_ids(self, path: str) -> bool:
        parsed_path = urlparse(self._graph_url(path)).path
        api_path = parsed_path.removeprefix("/v1.0")
        return any(api_path.startswith(prefix) for prefix in _OUTLOOK_PATH_PREFIXES)

    def _response_error(
        self,
        operation: str,
        *,
        policy: IntegrationRequestPolicy = IntegrationRequestPolicy.READ,
        original_error: Exception | None = None,
    ) -> IntegrationValidationError:
        return IntegrationValidationError(
            "Microsoft Graph returned an invalid response",
            provider_key=self._provider_key,
            operation=operation,
            original_error=original_error,
            failure_disposition=(
                IntegrationFailureDisposition.AMBIGUOUS
                if policy is not IntegrationRequestPolicy.READ
                else None
            ),
        )

    def _size_error(self, operation: str) -> IntegrationValidationError:
        return IntegrationValidationError(
            "Microsoft Graph download exceeds the size limit",
            provider_key=self._provider_key,
            operation=operation,
            failure_disposition=IntegrationFailureDisposition.REJECTED,
        )

    def _download_url_error(self, operation: str) -> IntegrationValidationError:
        return IntegrationValidationError(
            "Microsoft Graph download URL must use a public HTTPS destination",
            provider_key=self._provider_key,
            operation=operation,
            failure_disposition=IntegrationFailureDisposition.REJECTED,
        )
