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

import httpx2

from services.web.domain import WebFetchError

Resolver = Callable[[str, int], Awaitable[tuple[str, ...]]]

_STANDARD_PORTS = frozenset({80, 443})
_GZIP_CONTENT_TYPES = frozenset({"application/gzip", "application/x-gzip"})
_GZIP_MAGIC = b"\x1f\x8b"


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
