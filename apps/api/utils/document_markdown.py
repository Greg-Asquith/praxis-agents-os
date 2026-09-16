# apps/api/utils/document_markdown.py

"""Shared document-to-markdown conversion helpers."""

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from itertools import islice
from pathlib import PurePosixPath
from typing import Literal

from anyio import fail_after, to_process

from core.exceptions.general import AppValidationError
from services.assets.utils import normalize_content_type
from services.storage.paths import safe_filename
from utils.text_window import TextWindow, TextWindowError, utf8_window

TRUNCATION_MARKER = "\n\n[Truncated: document exceeds the converted size limit.]"
_TEXT_CONTENT_TYPES = frozenset({"application/json", "text/plain", "text/markdown", "text/csv"})
_HTML_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_CONTENT_TYPE_EXTENSIONS = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "text/html": ".html",
    "text/plain": ".txt",
    "text/markdown": ".md",
}


class DocumentConversionError(Exception):
    """Raised when a document cannot be converted to markdown."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class DocumentConversionResult:
    """Bounded Markdown and conversion facts returned by the worker."""

    markdown: str
    truncated: bool
    source: Literal["text", "converted"]


def document_content_type(content_type: str) -> str | None:
    """Returns the normalised type for a supported text or ingestible document."""
    from services.files.contract import contract_for_content_type

    try:
        entry = contract_for_content_type(content_type)
    except AppValidationError:
        return None
    return entry.content_type if entry.editable or entry.ingestible else None


async def convert_document_to_markdown(
    data: bytes,
    *,
    content_type: str,
    filename: str,
    max_bytes: int,
    timeout_seconds: float | None = None,
    strict_utf8: bool = False,
) -> str:
    """Converts bytes to bounded Markdown, replacing invalid UTF-8 unless strict."""
    result = await convert_document_to_markdown_result(
        data,
        content_type=content_type,
        filename=filename,
        max_bytes=max_bytes,
        timeout_seconds=timeout_seconds,
        strict_utf8=strict_utf8,
    )
    return result.markdown


async def convert_document_to_markdown_result(
    data: bytes,
    *,
    content_type: str,
    filename: str,
    max_bytes: int,
    timeout_seconds: float | None = None,
    strict_utf8: bool = False,
) -> DocumentConversionResult:
    """Converts bytes with actual truncation state and worker-side UTF-8 policy."""
    if timeout_seconds is not None:
        return await _run_document_process(
            partial(_convert_bounded_sync, data, content_type, filename, max_bytes, strict_utf8),
            timeout_seconds=timeout_seconds,
        )
    try:
        return await asyncio.to_thread(
            _convert_bounded_sync, data, content_type, filename, max_bytes, strict_utf8
        )
    except Exception as exc:
        raise DocumentConversionError("Document could not be converted to markdown") from exc


def _convert_bounded_sync(
    data: bytes, content_type: str, filename: str, max_bytes: int, strict_utf8: bool
) -> DocumentConversionResult:
    """Converts and bounds output before returning it from the worker."""
    markdown, source = _convert_text_sync(data, content_type, filename, strict_utf8)
    markdown, truncated = _bound_markdown(markdown, max_bytes=max_bytes)
    return DocumentConversionResult(markdown=markdown, truncated=truncated, source=source)


def _convert_text_sync(
    data: bytes, content_type: str, filename: str, strict_utf8: bool
) -> tuple[str, Literal["text", "converted"]]:
    normalized_content_type = normalize_content_type(content_type)
    errors = "strict" if strict_utf8 else "replace"
    source: Literal["text", "converted"] = "converted"
    if normalized_content_type in _TEXT_CONTENT_TYPES:
        markdown = data.decode("utf-8", errors=errors)
        source = "text"
    elif normalized_content_type in _HTML_CONTENT_TYPES:
        markdown = _convert_html_sync(data.decode("utf-8", errors=errors))
    else:
        extension = document_extension(filename, content_type=normalized_content_type)
        markdown = _convert_sync(data, extension)
    return markdown, source


def document_extension(filename: str, *, content_type: str | None = None) -> str:
    """Return a safe lower-case document extension."""
    suffix = PurePosixPath(safe_filename(filename)).suffix.lower()
    if suffix:
        return suffix
    if content_type:
        return _CONTENT_TYPE_EXTENSIONS.get(normalize_content_type(content_type), "")
    return ""


def _convert_sync(data: bytes, extension: str) -> str:
    import anydoc

    document_format = anydoc.format_from_extension(extension) if extension else None
    if document_format is None:
        document_format = anydoc.format_from_bytes(data)
    if document_format is None:
        raise DocumentConversionError("Document format could not be determined")
    text = anydoc.to_markdown_bytes(data, format=document_format)
    if not isinstance(text, str):
        raise DocumentConversionError("Markdown converter returned no text content")
    return text


def _convert_html_sync(html: str) -> str:
    from markdownify import ATX, markdownify

    # Markitdown's HTML converter selects ATX headings over markdownify's default.
    return markdownify(
        html,
        heading_style=ATX,
    ).strip()


def truncate_markdown(markdown: str, *, max_bytes: int) -> str:
    """Bounds Markdown at a UTF-8 boundary, including the truncation marker."""
    return _bound_markdown(markdown, max_bytes=max_bytes)[0]


def _bound_markdown(markdown: str, *, max_bytes: int) -> tuple[str, bool]:
    if max_bytes < 0:
        raise ValueError("Markdown byte limit must be non-negative")
    encoded = markdown.encode("utf-8")
    if len(encoded) <= max_bytes:
        return markdown, False

    marker_bytes = TRUNCATION_MARKER.encode("utf-8")
    if max_bytes < len(marker_bytes):
        return marker_bytes[:max_bytes].decode("utf-8", errors="ignore"), True
    allowed_content_bytes = max_bytes - len(marker_bytes)
    return encoded[:allowed_content_bytes].decode(
        "utf-8", errors="ignore"
    ) + TRUNCATION_MARKER, True


@dataclass(frozen=True)
class DocumentWindowResult:
    window: TextWindow
    source: Literal["text", "converted"]


@dataclass(frozen=True)
class DocumentFindResult:
    total_bytes: int
    matches: list[tuple[int, str]]
    has_more: bool


async def _run_document_process[T](operation: Callable[[], T], *, timeout_seconds: float) -> T:
    try:
        with fail_after(timeout_seconds):
            return await to_process.run_sync(operation, cancellable=True)
    except TextWindowError:
        raise
    except Exception:
        raise DocumentConversionError("Document could not be converted to markdown") from None


async def read_document_window(
    data: bytes,
    *,
    content_type: str,
    filename: str,
    offset: int,
    max_bytes: int,
    timeout_seconds: float,
) -> DocumentWindowResult:
    """Converts the whole document and returns only the requested window from the worker."""
    return await _run_document_process(
        partial(_read_window_sync, data, content_type, filename, offset, max_bytes),
        timeout_seconds=timeout_seconds,
    )


def _read_window_sync(
    data: bytes, content_type: str, filename: str, offset: int, max_bytes: int
) -> DocumentWindowResult:
    markdown, source = _convert_text_sync(data, content_type, filename, True)
    encoded = markdown.encode("utf-8")
    try:
        window = utf8_window(encoded, offset=offset, max_bytes=max_bytes)
    except TextWindowError as exc:
        raise TextWindowError(
            f"{exc} The converted content contains {len(encoded)} bytes."
        ) from None
    return DocumentWindowResult(window, source)


async def find_document_text(
    data: bytes,
    *,
    content_type: str,
    filename: str,
    query: str,
    limit: int,
    timeout_seconds: float,
) -> DocumentFindResult:
    """Searches the whole converted document and returns bounded excerpts from the worker."""
    return await _run_document_process(
        partial(_find_text_sync, data, content_type, filename, query, limit),
        timeout_seconds=timeout_seconds,
    )


def _find_text_sync(
    data: bytes, content_type: str, filename: str, query: str, limit: int
) -> DocumentFindResult:
    markdown, _ = _convert_text_sync(data, content_type, filename, True)
    found = list(islice(re.finditer(re.escape(query), markdown, re.IGNORECASE), limit + 1))
    matches = []
    previous_start = byte_offset = 0
    for match in found[:limit]:
        start = max(0, match.start() - 120)
        end = min(len(markdown), match.end() + 120)
        byte_offset += len(markdown[previous_start:start].encode("utf-8"))
        previous_start = start
        matches.append((byte_offset, markdown[start:end]))
    return DocumentFindResult(len(markdown.encode("utf-8")), matches, len(found) > limit)
