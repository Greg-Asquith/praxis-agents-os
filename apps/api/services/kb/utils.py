# apps/api/services/kb/utils.py

"""Knowledge-base ingestion helpers."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from pathlib import PurePosixPath
from urllib.parse import urljoin
from uuid import UUID

import httpx2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from core.settings import settings
from models.files import FileRevision
from services.files.contract import is_editable
from services.files.utils import private_ref_from_key
from services.storage.factory import get_storage_provider
from utils.digests import sha256_text as compute_markdown_hash
from utils.document_markdown import convert_document_to_markdown, truncate_markdown
from utils.tokens import estimate_tokens_by_character_count as estimate_tokens

__all__ = ["compute_markdown_hash", "estimate_tokens", "truncate_markdown"]

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_Resolver = Callable[[str, int], Awaitable[tuple[str, ...]]]


async def convert_html_to_markdown(
    data: bytes,
    *,
    content_type: str,
    source_url: str,
) -> str:
    """Convert fetched content through the shared document pipeline."""
    filename = PurePosixPath(httpx2.URL(source_url).path).name or "document.html"
    return await convert_document_to_markdown(
        data,
        content_type=content_type,
        filename=filename,
        max_bytes=settings.KB_MAX_DOCUMENT_BYTES,
    )


def _require_fetch_url(url: str) -> httpx2.URL:
    try:
        parsed = httpx2.URL(url)
    except Exception as exc:
        raise AppValidationError("Knowledge-base URL is invalid", field="url") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.host:
        raise AppValidationError(
            "Knowledge-base URL must use http or https",
            field="url",
        )
    if parsed.username or parsed.password:
        raise AppValidationError(
            "Knowledge-base URL must not include credentials",
            field="url",
        )
    return parsed


def _require_public_address(address: str) -> str:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError as exc:
        raise AppValidationError("Knowledge-base URL resolved to an invalid address") from exc
    if not parsed.is_global:
        raise AppValidationError(
            "Knowledge-base URL resolves to a non-public address",
            field="url",
        )
    return parsed.compressed


async def _resolve_public_addresses(host: str, port: int) -> tuple[str, ...]:
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
            raise AppValidationError(
                "Knowledge-base URL hostname could not be resolved",
                field="url",
            ) from exc
        addresses = tuple(dict.fromkeys(record[4][0] for record in records))
    else:
        addresses = (literal.compressed,)

    if not addresses:
        raise AppValidationError(
            "Knowledge-base URL hostname returned no addresses",
            field="url",
        )
    return tuple(_require_public_address(address) for address in addresses)


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


async def fetch_url(
    url: str,
    *,
    resolver: _Resolver = _resolve_public_addresses,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> tuple[bytes, str]:
    """Fetch a public URL while pinning every connection to a vetted address."""
    current_url = url
    redirects = 0

    async with httpx2.AsyncClient(
        transport=transport,
        timeout=settings.KB_URL_FETCH_TIMEOUT_SECONDS,
        trust_env=False,
    ) as client:
        while True:
            parsed = _require_fetch_url(current_url)
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            addresses = await resolver(parsed.host, port)
            if not addresses:
                raise AppValidationError(
                    "Knowledge-base URL hostname returned no addresses",
                    field="url",
                )
            vetted_addresses = tuple(_require_public_address(address) for address in addresses)
            pinned_url = parsed.copy_with(host=vetted_addresses[0])
            headers = {
                "Host": _host_header(parsed),
                "User-Agent": "Praxis-Agents-KB-Fetch/1.0",
                "Accept": "*/*",
            }
            extensions = {"sni_hostname": parsed.host}

            async with client.stream(
                "GET",
                pinned_url,
                headers=headers,
                extensions=extensions,
                follow_redirects=False,
            ) as response:
                if response.status_code in _REDIRECT_STATUSES:
                    location = response.headers.get("location")
                    if not location:
                        raise AppValidationError(
                            "Knowledge-base URL redirect has no destination",
                            field="url",
                        )
                    if redirects >= settings.KB_URL_MAX_REDIRECTS:
                        raise AppValidationError(
                            "Knowledge-base URL exceeded the redirect limit",
                            field="url",
                        )
                    redirects += 1
                    current_url = urljoin(current_url, location)
                    continue

                try:
                    response.raise_for_status()
                except httpx2.HTTPStatusError as exc:
                    raise AppValidationError(
                        "Knowledge-base URL returned an unsuccessful response",
                        field="url",
                        details={"status_code": response.status_code},
                    ) from exc

                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > settings.KB_URL_MAX_BYTES:
                        raise AppValidationError(
                            "Knowledge-base URL response exceeds the size limit",
                            field="url",
                        )
                    body.extend(chunk)
                content_type = response.headers.get("content-type", "application/octet-stream")
                return bytes(body), content_type


async def get_revision_markdown(db: AsyncSession, file_revision_id: UUID) -> str:
    """Read extracted or editable text for one already-authorized file revision."""
    revision = await db.scalar(select(FileRevision).where(FileRevision.id == file_revision_id))
    if revision is None:
        raise AppValidationError(
            "File revision does not exist",
            field="file_revision_id",
        )

    object_key = revision.markdown_object_key
    if object_key is None and is_editable(revision.content_type):
        object_key = revision.object_key
    if object_key is None:
        raise AppValidationError(
            "File extraction is not ready",
            field="file_revision_id",
        )

    data = await get_storage_provider().get_object(private_ref_from_key(object_key))
    return data.decode("utf-8", errors="replace")
