# apps/api/services/web/utils.py

"""Public-address validation, connection pinning, and limits for web fetches."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import zlib
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal

import httpx2

from core.settings import settings
from services.web.domain import FetchedResponse, WebFetchError
from utils.document_markdown import document_content_type

Resolver = Callable[[str, int], Awaitable[tuple[str, ...]]]

_STANDARD_PORTS = frozenset({80, 443})
_GZIP_CONTENT_TYPES = frozenset({"application/gzip", "application/x-gzip"})
_GZIP_MAGIC = b"\x1f\x8b"
_HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_TEXT_TYPES = frozenset(
    {
        "application/ecmascript",
        "application/javascript",
        "application/json",
        "application/x-javascript",
        "application/xml",
    }
)
_HTML_SNIFF_PREFIXES = (b"<!doctype html", b"<html")
_FILE_NAME_MAX_CHARS = 120

# How a fetched body is returned: an HTML page, verbatim text, a converted document, or not at all.
ContentKind = Literal["html", "text", "document", "unsupported"]


@dataclass(frozen=True)
class PinnedRequest:
    """A request target bound to a vetted address while keeping the original Host and TLS name."""

    url: httpx2.URL
    headers: dict[str, str]
    extensions: dict[str, str]


def validate_public_url(url: str, *, standard_ports_only: bool = False) -> httpx2.URL:
    """Validates an HTTP(S) URL without credentials, returning the parsed URL.

    Rejects `localhost` and literal non-public addresses before any DNS lookup.
    If `standard_ports_only` is true, also rejects ports other than 80 and 443.
    """
    try:
        parsed = httpx2.URL(url)
    except Exception as exc:
        raise WebFetchError("URL is invalid", error_class="invalid_url") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.host:
        raise WebFetchError("URL must use http or https", error_class="invalid_url")
    if parsed.username or parsed.password:
        raise WebFetchError("URL must not include credentials", error_class="invalid_url")
    if standard_ports_only and parsed.port not in {None, *_STANDARD_PORTS}:
        raise WebFetchError("URL must use port 80 or 443", error_class="unsupported_port")
    if parsed.host.lower().rstrip(".") == "localhost":
        raise WebFetchError("URL must use a public host", error_class="non_public_address")
    try:
        literal = ipaddress.ip_address(parsed.host)
    except ValueError:
        return parsed
    require_public_address(literal.compressed)
    return parsed


def require_public_address(address: str) -> str:
    """Returns the compressed form of a globally routable address, rejecting any other."""
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError as exc:
        raise WebFetchError(
            "URL resolved to an invalid address", error_class="non_public_address"
        ) from exc
    if not parsed.is_global:
        raise WebFetchError(
            "URL resolves to a non-public address", error_class="non_public_address"
        )
    return parsed.compressed


async def resolve_public_addresses(host: str, port: int) -> tuple[str, ...]:
    """Returns every address for a host, rejecting the host if any address is non-public."""
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        try:
            records = await asyncio.get_running_loop().getaddrinfo(
                host,
                port,
                type=socket.SOCK_STREAM,
            )
        except OSError as exc:
            raise WebFetchError(
                "URL hostname could not be resolved", error_class="dns_failure"
            ) from exc
        addresses = tuple(dict.fromkeys(record[4][0] for record in records))
    else:
        addresses = (literal.compressed,)
    return tuple(require_public_address(address) for address in addresses)


async def pin_public_request(
    url: httpx2.URL,
    *,
    resolver: Resolver = resolve_public_addresses,
) -> PinnedRequest:
    """Resolves and vets a validated URL's host, then pins the request to its first address."""
    port = url.port or (443 if url.scheme == "https" else 80)
    addresses = await resolver(url.host, port)
    if not addresses:
        raise WebFetchError("URL hostname returned no addresses", error_class="dns_failure")
    vetted = tuple(require_public_address(address) for address in addresses)
    return PinnedRequest(
        url=url.copy_with(host=vetted[0]),
        headers={"Host": _host_header(url)},
        extensions={"sni_hostname": url.host},
    )


def blocked_domain_for_host(host: str, blocked_domains: Iterable[str]) -> str | None:
    """Returns the denylisted domain that matches a host or one of its parents."""
    normalized = host.lower().rstrip(".")
    for domain in blocked_domains:
        if normalized == domain or normalized.endswith(f".{domain}"):
            return domain
    return None


def configured_blocked_domains() -> tuple[str, ...]:
    """Returns the domains in `WEB_FETCH_BLOCKED_DOMAINS`, which settings validation normalises."""
    return tuple(domain for domain in settings.WEB_FETCH_BLOCKED_DOMAINS.split(",") if domain)


class HostLimiter:
    """Bounds concurrent requests to each host for one owner, such as an agent run.

    Create one per owner inside its event loop; the semaphores bind to that loop.
    """

    def __init__(self, per_host: int) -> None:
        self._per_host = per_host
        self._semaphores: dict[str, asyncio.Semaphore] = {}

    @asynccontextmanager
    async def hold(self, host: str) -> AsyncIterator[None]:
        """Waits for a free slot for the host and holds it until the block exits."""
        key = host.lower().rstrip(".")
        semaphore = self._semaphores.setdefault(key, asyncio.Semaphore(self._per_host))
        async with semaphore:
            yield


class RunFetchBudget:
    """Counts the URLs one agent run fetches and bounds its requests to each host."""

    def __init__(self, *, max_urls: int, per_host: int) -> None:
        self.max_urls = max_urls
        self.used = 0
        self.limiter = HostLimiter(per_host)

    @classmethod
    def from_settings(cls) -> RunFetchBudget:
        return cls(
            max_urls=settings.WEB_FETCH_RUN_URL_BUDGET,
            per_host=settings.WEB_FETCH_HOST_CONCURRENCY,
        )

    @classmethod
    def for_page_speed(cls) -> RunFetchBudget:
        """Creates the budget of PageSpeed Insights tests; Google sends those requests."""
        return cls(
            max_urls=settings.PAGESPEED_RUN_BUDGET,
            per_host=settings.WEB_FETCH_HOST_CONCURRENCY,
        )

    @property
    def remaining(self) -> int:
        return self.max_urls - self.used

    def take(self, count: int = 1) -> bool:
        """Reserves `count` URLs, returning false without reserving any when too few remain."""
        if self.used + count > self.max_urls:
            return False
        self.used += count
        return True


def content_kind(response: FetchedResponse) -> ContentKind:
    """Classifies a fetched body by its media type, sniffing HTML when the type is missing."""
    media_type = response.content_type.partition(";")[0].strip().lower()
    if media_type in _HTML_TYPES:
        return "html"
    if response.gunzipped or media_type.startswith("text/") or media_type in _TEXT_TYPES:
        return "text"
    if media_type.endswith(("+json", "+xml")):
        return "text"
    if document_content_type(media_type) is not None:
        return "document"
    if media_type == "application/octet-stream" and response.body.lstrip()[:15].lower().startswith(
        _HTML_SNIFF_PREFIXES
    ):
        return "html"
    return "unsupported"


def file_content_type(response: FetchedResponse) -> str | None:
    """Returns the Files type a successful body saves as, or None when it can't be saved."""
    if not 200 <= response.status < 300:
        return None
    kind = content_kind(response)
    if kind == "html":
        return "text/html"
    if kind == "text":
        media_type = response.content_type.partition(";")[0].strip().lower()
        editable = None if response.gunzipped else document_content_type(media_type)
        return editable or "text/plain"
    if kind == "document":
        return document_content_type(response.content_type)
    return None


def page_file_name(url: str) -> str:
    """Returns a readable File name from a URL's host and path, such as `example.com - pricing`."""
    parsed = httpx2.URL(url)
    segments = [segment for segment in parsed.path.split("/") if segment]
    return " - ".join([parsed.host, *segments])[:_FILE_NAME_MAX_CHARS]


def is_gzip_body(body: bytes, *, content_type: str, path: str) -> bool:
    """Checks whether a response body is a gzip file rather than gzip transfer encoding."""
    media_type = content_type.partition(";")[0].strip().lower()
    return body.startswith(_GZIP_MAGIC) and (
        media_type in _GZIP_CONTENT_TYPES or path.lower().endswith(".gz")
    )


def gunzip_bounded(body: bytes, *, max_bytes: int) -> bytes:
    """Returns a decompressed gzip body, stopping once output passes `max_bytes`."""
    decompressor = zlib.decompressobj(wbits=31)
    try:
        output = decompressor.decompress(body, max_bytes + 1)
    except zlib.error as exc:
        raise WebFetchError(
            "URL returned an unreadable gzip file",
            error_class="protocol_failure",
        ) from exc
    if len(output) > max_bytes:
        raise WebFetchError(
            "URL response exceeds the size limit",
            error_class="too_large",
        )
    return output


def _host_header(url: httpx2.URL) -> str:
    host = url.host
    try:
        is_ipv6_literal = ipaddress.ip_address(host).version == 6
    except ValueError:
        is_ipv6_literal = False
    if is_ipv6_literal:
        host = f"[{host}]"

    default_port = 443 if url.scheme == "https" else 80
    return host if url.port in {None, default_port} else f"{host}:{url.port}"
