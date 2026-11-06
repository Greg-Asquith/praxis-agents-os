# apps/api/utils/document_markdown.py

"""Shared document-to-markdown conversion, run in the document worker pool."""

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Literal

from core.exceptions.general import AppValidationError
from services.assets.utils import normalize_content_type
from services.documents.markdown import bound_markdown
from services.documents.worker import (
    MARKDOWN_FORMAT,
    DocumentRequestError,
    DocumentWorkerResult,
    get_document_worker_pool,
)
from services.storage.paths import safe_filename
from utils.text_window import TextWindow, TextWindowError

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
    strict_utf8: bool = False,
    web_page: bool = False,
) -> str:
    """Converts bytes to bounded Markdown, replacing invalid UTF-8 unless strict."""
    result = await convert_document_to_markdown_result(
        data,
        content_type=content_type,
        filename=filename,
        max_bytes=max_bytes,
        strict_utf8=strict_utf8,
        web_page=web_page,
    )
    return result.markdown


async def convert_document_to_markdown_result(
    data: bytes,
    *,
    content_type: str,
    filename: str,
    max_bytes: int,
    strict_utf8: bool = False,
    web_page: bool = False,
) -> DocumentConversionResult:
    """Converts bytes in a worker; `web_page` keeps a fetched page's main content only."""
    result = await _run(
        "to_markdown",
        data,
        content_type,
        filename,
        strict_utf8=strict_utf8,
        web_page=web_page,
        max_bytes=max_bytes,
    )
    return DocumentConversionResult(
        markdown=(result.data or b"").decode("utf-8"),
        truncated=result.value["truncated"],
        source=result.value["source"],
    )


def document_extension(filename: str, *, content_type: str | None = None) -> str:
    """Return a safe lower-case document extension."""
    suffix = PurePosixPath(safe_filename(filename)).suffix.lower()
    if suffix:
        return suffix
    if content_type:
        return _CONTENT_TYPE_EXTENSIONS.get(normalize_content_type(content_type), "")
    return ""


def truncate_markdown(markdown: str, *, max_bytes: int) -> str:
    """Bounds Markdown at a UTF-8 boundary, including the truncation marker."""
    return bound_markdown(markdown, max_bytes=max_bytes)[0]


@dataclass(frozen=True)
class DocumentWindowResult:
    window: TextWindow
    source: Literal["text", "converted"]


@dataclass(frozen=True)
class DocumentFindResult:
    total_bytes: int
    matches: list[tuple[int, str]]
    has_more: bool


async def read_document_window(
    data: bytes,
    *,
    content_type: str,
    filename: str,
    offset: int,
    max_bytes: int,
) -> DocumentWindowResult:
    """Converts the whole document and returns only the requested window from the worker."""
    result = await _run(
        "markdown_window",
        data,
        content_type,
        filename,
        strict_utf8=True,
        offset=offset,
        max_bytes=max_bytes,
    )
    value = result.value
    window = TextWindow(
        content=value["content"],
        offset=value["offset"],
        end_offset=value["end_offset"],
        total_bytes=value["total_bytes"],
    )
    return DocumentWindowResult(window, value["source"])


async def find_document_text(
    data: bytes,
    *,
    content_type: str,
    filename: str,
    query: str,
    limit: int,
) -> DocumentFindResult:
    """Searches the whole converted document and returns bounded excerpts from the worker."""
    result = await _run(
        "find_markdown", data, content_type, filename, strict_utf8=True, query=query, limit=limit
    )
    value = result.value
    return DocumentFindResult(
        total_bytes=value["total_bytes"],
        matches=[(offset, excerpt) for offset, excerpt in value["matches"]],
        has_more=value["has_more"],
    )


async def _run(
    operation: str,
    data: bytes,
    content_type: str,
    filename: str,
    *,
    strict_utf8: bool,
    web_page: bool = False,
    **args: Any,
) -> DocumentWorkerResult:
    try:
        normalized = normalize_content_type(content_type)
        args |= {
            "content_type": normalized,
            "extension": document_extension(filename, content_type=normalized),
            "strict_utf8": strict_utf8,
            "web_page": web_page,
        }
        return await get_document_worker_pool().run(
            operation, document_format=MARKDOWN_FORMAT, data=data, args=args
        )
    except DocumentRequestError as exc:
        # Only window reads raise request errors: the offset or size doesn't fit the content.
        raise TextWindowError(exc.message) from None
    except AppValidationError:
        raise DocumentConversionError("Document could not be converted to markdown") from None
