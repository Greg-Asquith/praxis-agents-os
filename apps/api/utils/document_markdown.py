# apps/api/utils/document_markdown.py

"""Shared document-to-markdown conversion helpers."""

import asyncio
from pathlib import PurePosixPath

from services.assets.utils import normalize_content_type
from services.storage.paths import safe_filename

TRUNCATION_MARKER = "\n\n[Truncated: document exceeds the converted size limit.]"
_TEXT_CONTENT_TYPES = frozenset({"text/plain", "text/markdown"})
_HTML_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_CONTENT_TYPE_EXTENSIONS = {
    "application/pdf": ".pdf",
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


async def convert_document_to_markdown(
    data: bytes,
    *,
    content_type: str,
    filename: str,
    max_bytes: int,
) -> str:
    """Convert document bytes into markdown, enforcing the supplied byte cap."""
    normalized_content_type = normalize_content_type(content_type)
    if normalized_content_type in _TEXT_CONTENT_TYPES:
        markdown = data.decode("utf-8", errors="replace")
    else:
        try:
            if normalized_content_type in _HTML_CONTENT_TYPES:
                markdown = await asyncio.to_thread(_convert_html_sync, data)
            else:
                extension = document_extension(filename, content_type=normalized_content_type)
                markdown = await asyncio.to_thread(_convert_sync, data, extension)
        except Exception as exc:
            raise DocumentConversionError("Document could not be converted to markdown") from exc

    return truncate_markdown(markdown, max_bytes=max_bytes)


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


def _convert_html_sync(data: bytes) -> str:
    from markdownify import ATX, markdownify

    # Markitdown's HTML converter selects ATX headings over markdownify's default.
    return markdownify(
        data.decode("utf-8", errors="replace"),
        heading_style=ATX,
    ).strip()


def truncate_markdown(markdown: str, *, max_bytes: int) -> str:
    """Truncate markdown at a UTF-8 character boundary when it exceeds max_bytes."""
    encoded = markdown.encode("utf-8")
    if len(encoded) <= max_bytes:
        return markdown

    marker_bytes = TRUNCATION_MARKER.encode("utf-8")
    allowed_content_bytes = max(0, max_bytes - len(marker_bytes))
    truncated = encoded[:allowed_content_bytes]
    while truncated:
        try:
            return truncated.decode("utf-8") + TRUNCATION_MARKER
        except UnicodeDecodeError:
            truncated = truncated[:-1]
    return TRUNCATION_MARKER
