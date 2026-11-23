# apps/api/services/kb/utils.py

"""Knowledge-base ingestion helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import PurePosixPath
from uuid import UUID

import httpx2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from core.settings import settings
from models.files import FileRevision
from models.kb import KBDocument
from services.files.contract import is_editable
from services.files.utils import private_ref_from_key
from services.kb.domain import (
    KB_SOURCE_INTEGRATION,
    KB_SOURCE_UPLOAD,
    KB_SOURCE_URL,
    FetchedUrl,
    KBSourceUnavailableError,
)
from services.storage.factory import get_storage_provider
from services.web.domain import FetchedResponse
from services.web.fetch import fetch_url as fetch_public_url
from services.web.utils import Resolver, resolve_public_addresses, validate_public_url
from utils.digests import sha256_text as compute_markdown_hash
from utils.document_markdown import convert_document_to_markdown, truncate_markdown
from utils.tokens import estimate_tokens_by_character_count as estimate_tokens

__all__ = [
    "compute_markdown_hash",
    "document_origin_ref",
    "estimate_tokens",
    "truncate_markdown",
]

_DEFINITIVE_URL_STATUS_CODES = {
    401: "access_lost",
    403: "access_lost",
    404: "not_found",
    410: "not_found",
}
_MAX_ETAG_CHARS = 256


def require_kb_workspace_id(workspace_id: UUID | None) -> UUID:
    """Require tenant scope for a knowledge-base operation."""
    if workspace_id is None:
        raise AppValidationError(
            "Knowledge-base operations require a workspace",
            field="workspace_id",
        )
    return workspace_id


def document_origin_ref(document: KBDocument) -> str | None:
    """Return the durable source reference used for write provenance."""
    if document.source_type == KB_SOURCE_URL:
        return document.external_url
    if document.source_type == KB_SOURCE_INTEGRATION:
        return document.external_url
    if document.source_type == KB_SOURCE_UPLOAD and document.file_revision_id is not None:
        return str(document.file_revision_id)
    return None


def validate_source_url(url: str | None) -> str:
    """Normalizes and validates a URL before a source document is created."""
    if url is None or not url.strip():
        raise AppValidationError("URL documents require a URL", field="url")
    normalized = url.strip()
    validate_public_url(normalized)
    return normalized


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
        content_type=content_type.partition(";")[0],
        filename=filename,
        max_bytes=settings.KB_MAX_DOCUMENT_BYTES,
        web_page=True,
    )


async def fetch_url(
    url: str,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    resolver: Resolver = resolve_public_addresses,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> FetchedUrl:
    """Fetches a URL source, sending stored validators on the first hop only.

    Raises:
        KBSourceUnavailableError: If the source answers `401`, `403`, `404`, or `410`.
        AppValidationError: If the fetch is refused or fails, or the source answers
            another unsuccessful status.
    """
    validators = {}
    if etag is not None:
        validators["If-None-Match"] = etag
    if last_modified is not None:
        validators["If-Modified-Since"] = last_modified
    response = await fetch_public_url(
        url,
        timeout_seconds=settings.KB_URL_FETCH_TIMEOUT_SECONDS,
        max_redirects=settings.KB_URL_MAX_REDIRECTS,
        max_bytes=settings.KB_URL_MAX_BYTES,
        body="success",
        first_hop_headers=validators,
        resolver=resolver,
        transport=transport,
    )
    return _fetched_source(response, etag=etag, last_modified=last_modified)


def _fetched_source(
    response: FetchedResponse,
    *,
    etag: str | None,
    last_modified: str | None,
) -> FetchedUrl:
    error_code = _DEFINITIVE_URL_STATUS_CODES.get(response.status)
    if error_code is not None:
        raise KBSourceUnavailableError(error_code=error_code, status_code=response.status)
    not_modified = response.status == 304
    if not not_modified and not 200 <= response.status < 300:
        raise AppValidationError(
            "Knowledge-base URL returned an unsuccessful response",
            field="url",
            details={"status_code": response.status},
        )
    return FetchedUrl(
        data=response.body,
        content_type=response.content_type,
        etag=_response_etag(response, fallback=etag),
        last_modified=_response_last_modified(response, fallback=last_modified),
        not_modified=not_modified,
    )


def _response_etag(response: FetchedResponse, *, fallback: str | None) -> str | None:
    raw_etag = response.headers.get("etag")
    if raw_etag is None:
        return _bounded_etag(fallback) if response.status == 304 else None
    return _bounded_etag(raw_etag)


def _bounded_etag(value: str | None) -> str | None:
    if value is None or len(value) > _MAX_ETAG_CHARS:
        return None
    return value


def _response_last_modified(
    response: FetchedResponse,
    *,
    fallback: str | None,
) -> str | None:
    raw_last_modified = response.headers.get("last-modified")
    if raw_last_modified is None and response.status == 304:
        return fallback
    return raw_last_modified


def parse_last_modified(value: str | None) -> datetime | None:
    """Returns a UTC source timestamp from an HTTP Last-Modified value."""
    if value is None:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


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
