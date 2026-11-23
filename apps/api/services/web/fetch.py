# apps/api/services/web/fetch.py

"""Bounded GETs to public URLs, pinned to vetted addresses on every hop."""

from __future__ import annotations

import asyncio
import ssl
import time
from collections.abc import Iterable, Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx2

from services.web.domain import (
    RESPONSE_HEADER_ALLOWLIST,
    USER_AGENT_HEADERS,
    BodyMode,
    FetchedResponse,
    RedirectHop,
    UserAgent,
    WebFetchError,
)
from services.web.utils import (
    HostLimiter,
    Resolver,
    ascii_host,
    blocked_domain_for_host,
    gunzip_bounded,
    is_gzip_body,
    pin_public_request,
    resolve_public_addresses,
    validate_public_url,
)

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_MAX_HEADER_CHARS = 2_048


async def fetch_url(
    url: str,
    *,
    timeout_seconds: float,
    max_redirects: int,
    max_bytes: int,
    user_agent: UserAgent = "praxis",
    body: BodyMode = "always",
    gunzip: bool = False,
    standard_ports_only: bool = False,
    blocked_domains: Iterable[str] = (),
    first_hop_headers: Mapping[str, str] | None = None,
    limiter: HostLimiter | None = None,
    resolver: Resolver = resolve_public_addresses,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> FetchedResponse:
    """Fetches a public URL and returns its final response, whatever the status.

    Each hop is validated, checked against `blocked_domains`, resolved, and
    pinned before it connects. `timeout_seconds` bounds the whole call,
    including resolution, redirects, and reading. `first_hop_headers` carries
    conditional request headers that must not follow a redirect.

    Raises:
        WebFetchError: If the URL or a redirect target is refused, the
            transport fails, the deadline passes, or the body exceeds
            `max_bytes`. The error carries the redirects followed so far.
    """
    redirects: list[RedirectHop] = []
    request = _FetchRequest(
        url=url,
        max_redirects=max_redirects,
        max_bytes=max_bytes,
        user_agent=user_agent,
        body=body,
        gunzip=gunzip,
        standard_ports_only=standard_ports_only,
        blocked_domains=tuple(blocked_domains),
        first_hop_headers=dict(first_hop_headers or {}),
        limiter=limiter,
        resolver=resolver,
    )
    try:
        async with asyncio.timeout(timeout_seconds):
            async with httpx2.AsyncClient(
                transport=transport,
                timeout=timeout_seconds,
                trust_env=False,
            ) as client:
                return await _follow(client, request, redirects)
    except WebFetchError as exc:
        exc.redirects = tuple(redirects)
        raise
    except (TimeoutError, httpx2.TimeoutException) as exc:
        raise WebFetchError(
            "URL did not respond in time",
            error_class="timeout",
            redirects=tuple(redirects),
        ) from exc
    except httpx2.ConnectError as exc:
        tls = _caused_by_tls(exc)
        raise WebFetchError(
            "URL failed its secure connection check" if tls else "URL refused the connection",
            error_class="tls_failure" if tls else "connect_failure",
            redirects=tuple(redirects),
        ) from exc
    except httpx2.TransportError as exc:
        raise WebFetchError(
            "URL returned an unreadable response",
            error_class="protocol_failure",
            redirects=tuple(redirects),
        ) from exc


@dataclass(frozen=True)
class _FetchRequest:
    url: str
    max_redirects: int
    max_bytes: int
    user_agent: UserAgent
    body: BodyMode
    gunzip: bool
    standard_ports_only: bool
    blocked_domains: tuple[str, ...]
    first_hop_headers: dict[str, str]
    limiter: HostLimiter | None
    resolver: Resolver


async def _follow(
    client: httpx2.AsyncClient,
    request: _FetchRequest,
    redirects: list[RedirectHop],
) -> FetchedResponse:
    started = time.perf_counter()
    current_url = request.url
    while True:
        # Requests are pinned to addresses, so a kept cookie would follow a redirect to another host.
        client.cookies.clear()
        target = validate_public_url(
            current_url,
            standard_ports_only=request.standard_ports_only,
        )
        host = ascii_host(target)
        blocked = blocked_domain_for_host(host, request.blocked_domains)
        if blocked is not None:
            raise WebFetchError(f"URL domain '{blocked}' is blocked", error_class="blocked_domain")
        pinned = await pin_public_request(target, resolver=request.resolver)
        headers = {
            **pinned.headers,
            "User-Agent": USER_AGENT_HEADERS[request.user_agent],
            "Accept": "*/*",
        }
        if not redirects:
            headers.update(request.first_hop_headers)

        async with AsyncExitStack() as stack:
            if request.limiter is not None:
                await stack.enter_async_context(request.limiter.hold(host))
            hop_started = time.perf_counter()
            response = await stack.enter_async_context(
                client.stream(
                    "GET",
                    pinned.url,
                    headers=headers,
                    extensions=pinned.extensions,
                    follow_redirects=False,
                )
            )
            first_byte_ms = _elapsed_ms(hop_started)
            next_url = _redirect_target(
                response,
                current_url=current_url,
                redirects=redirects,
                max_redirects=request.max_redirects,
            )
            if next_url is not None:
                current_url = next_url
                continue
            data = await _read_body(
                response,
                mode=request.body,
                max_bytes=request.max_bytes,
            )

        gunzipped = request.gunzip and is_gzip_body(
            data,
            content_type=response.headers.get("content-type", ""),
            path=target.path,
        )
        if gunzipped:
            data = gunzip_bounded(data, max_bytes=request.max_bytes)
        return FetchedResponse(
            requested_url=request.url,
            final_url=current_url,
            status=response.status_code,
            headers=_allowlisted_headers(response.headers),
            redirects=tuple(redirects),
            user_agent=request.user_agent,
            body=data,
            body_read=_should_read_body(request.body, response.status_code),
            gunzipped=gunzipped,
            time_to_first_byte_ms=first_byte_ms,
            elapsed_ms=_elapsed_ms(started),
        )


def _redirect_target(
    response: httpx2.Response,
    *,
    current_url: str,
    redirects: list[RedirectHop],
    max_redirects: int,
) -> str | None:
    if response.status_code not in _REDIRECT_STATUSES:
        return None
    location = response.headers.get("location")
    if not location:
        raise WebFetchError(
            "URL redirect has no destination",
            error_class="redirect_without_location",
        )
    target = urljoin(current_url, location)
    redirects.append(RedirectHop(url=current_url, status=response.status_code, location=target))
    if len(redirects) > max_redirects:
        raise WebFetchError(
            "URL exceeded the redirect limit",
            error_class="too_many_redirects",
        )
    return target


def _should_read_body(mode: BodyMode, status: int) -> bool:
    return mode == "always" or (mode == "success" and 200 <= status < 300)


async def _read_body(
    response: httpx2.Response,
    *,
    mode: BodyMode,
    max_bytes: int,
) -> bytes:
    if not _should_read_body(mode, response.status_code):
        return b""
    data = bytearray()
    async for chunk in response.aiter_bytes():
        if len(data) + len(chunk) > max_bytes:
            raise WebFetchError(
                "URL response exceeds the size limit",
                error_class="too_large",
            )
        data.extend(chunk)
    return bytes(data)


def _allowlisted_headers(headers: httpx2.Headers) -> dict[str, str]:
    return {
        name: value[:_MAX_HEADER_CHARS]
        for name in RESPONSE_HEADER_ALLOWLIST
        if (value := headers.get(name)) is not None
    }


def _caused_by_tls(exc: BaseException) -> bool:
    current: BaseException | None = exc
    while current is not None:
        if isinstance(current, ssl.SSLError):
            return True
        current = current.__cause__ or current.__context__
    return False


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)
