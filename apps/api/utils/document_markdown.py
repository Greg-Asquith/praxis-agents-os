# apps/api/utils/document_markdown.py

"""Shared document-to-markdown conversion helpers."""

import asyncio
import io
from pathlib import PurePosixPath

from services.assets.utils import normalize_content_type
from services.storage.paths import safe_filename

TRUNCATION_MARKER = "\n\n[Truncated: document exceeds the converted size limit.]"
_TEXT_CONTENT_TYPES = frozenset({"text/plain", "text/markdown"})
_CONTENT_TYPE_EXTENSIONS = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
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
        extension = document_extension(filename, content_type=normalized_content_type)
        try:
            markdown = await asyncio.to_thread(_convert_sync, data, extension)
        except Exception as exc:
            raise DocumentConversionError(
                "Document could not be converted to markdown"
            ) from exc

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
    from markitdown import MarkItDown

    result = MarkItDown().convert_stream(io.BytesIO(data), file_extension=extension or None)
    text = getattr(result, "text_content", None)
    if text is None:
        text = getattr(result, "markdown", None)
    if not isinstance(text, str):
        raise DocumentConversionError("Markdown converter returned no text content")
    return text


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
