# apps/api/services/documents/markdown.py

"""Markdown conversion, windows, and search. Imported only inside the document worker."""

import io
import re
import zipfile
from itertools import islice
from typing import Any

from services.documents.precheck import OFFICE_FORMATS, PackageLimits, precheck_package
from services.documents.reading import DocumentRequestError
from utils.text_window import TextWindowError, utf8_window

type HandlerResult = tuple[dict[str, Any], bytes | None]

TRUNCATION_MARKER = "\n\n[Truncated: document exceeds the converted size limit.]"
TEXT_CONTENT_TYPES = frozenset({"application/json", "text/plain", "text/markdown", "text/csv"})
HTML_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})
_FIND_CONTEXT_CHARS = 120
_PAGE_BOILERPLATE_TAGS = [
    "aside",
    "button",
    "dialog",
    "footer",
    "form",
    "header",
    "iframe",
    "nav",
    "noscript",
    "script",
    "style",
    "svg",
    "template",
]
_PAGE_BOILERPLATE_ROLES = frozenset(
    {"alert", "banner", "complementary", "contentinfo", "dialog", "navigation", "search"}
)
# Bracket and parenthesis exclusions keep failed matches from rescanning, so cleanup is linear.
_MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\[\]]*)\]\([^()]*\)")
_MARKDOWN_EMPTY_LINK_RE = re.compile(r"\[\s*\]\([^()]*\)")
_EXTRA_BLANK_LINES_RE = re.compile(r"\n{3,}")


def to_markdown(
    _format: str, args: dict[str, Any], data: bytes, limits: PackageLimits
) -> HandlerResult:
    """Returns the bounded Markdown as the payload."""
    markdown, source = _convert(data, args, limits)
    markdown, truncated = bound_markdown(markdown, max_bytes=args["max_bytes"])
    return {"truncated": truncated, "source": source}, markdown.encode("utf-8")


def markdown_window(
    _format: str, args: dict[str, Any], data: bytes, limits: PackageLimits
) -> HandlerResult:
    """Converts the whole document and returns one UTF-8 window of it."""
    markdown, source = _convert(data, args, limits)
    encoded = markdown.encode("utf-8")
    try:
        window = utf8_window(encoded, offset=args["offset"], max_bytes=args["max_bytes"])
    except TextWindowError as exc:
        raise DocumentRequestError(
            f"{exc} The converted content contains {len(encoded)} bytes."
        ) from None
    return {
        "content": window.content,
        "offset": window.offset,
        "end_offset": window.end_offset,
        "total_bytes": window.total_bytes,
        "source": source,
    }, None


def find_markdown(
    _format: str, args: dict[str, Any], data: bytes, limits: PackageLimits
) -> HandlerResult:
    """Searches the whole converted document and returns bounded excerpts."""
    markdown, _ = _convert(data, args, limits)
    limit = args["limit"]
    found = list(islice(re.finditer(re.escape(args["query"]), markdown, re.IGNORECASE), limit + 1))
    matches = []
    previous_start = byte_offset = 0
    for match in found[:limit]:
        start = max(0, match.start() - _FIND_CONTEXT_CHARS)
        end = min(len(markdown), match.end() + _FIND_CONTEXT_CHARS)
        byte_offset += len(markdown[previous_start:start].encode("utf-8"))
        previous_start = start
        matches.append([byte_offset, markdown[start:end]])
    return {
        "total_bytes": len(markdown.encode("utf-8")),
        "matches": matches,
        "has_more": len(found) > limit,
    }, None


def bound_markdown(markdown: str, *, max_bytes: int) -> tuple[str, bool]:
    """Bounds Markdown at a UTF-8 boundary, including the truncation marker."""
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


def strip_markdown_noise(markdown: str) -> str:
    """Replaces image markup with alt text and drops empty links converted pages leave behind."""
    cleaned = _MARKDOWN_IMAGE_RE.sub(r"\1", markdown)
    cleaned = _MARKDOWN_EMPTY_LINK_RE.sub("", cleaned)
    return _EXTRA_BLANK_LINES_RE.sub("\n\n", cleaned).strip("\n")


def _convert(data: bytes, args: dict[str, Any], limits: PackageLimits) -> tuple[str, str]:
    content_type = args["content_type"]
    errors = "strict" if args["strict_utf8"] else "replace"
    if content_type in TEXT_CONTENT_TYPES:
        return data.decode("utf-8", errors=errors), "text"
    if content_type not in HTML_CONTENT_TYPES:
        return _convert_document(data, args["extension"], limits), "converted"
    if not args["web_page"]:
        return _html_to_markdown(data.decode("utf-8", errors=errors)), "converted"
    markdown = _html_to_markdown(_main_page_content(data).decode("utf-8", errors=errors))
    return strip_markdown_noise(markdown), "converted"


def _convert_document(data: bytes, extension: str, limits: PackageLimits) -> str:
    import anydoc

    document_format = anydoc.format_from_extension(extension) if extension else None
    if document_format is None:
        document_format = anydoc.format_from_bytes(data)
    if document_format is None:
        raise ValueError("Document format could not be determined")
    # anydoc labels legacy .xls as xlsx, so only zip packages are prechecked.
    if document_format in OFFICE_FORMATS and zipfile.is_zipfile(io.BytesIO(data)):
        precheck_package(data, limits)
    text = anydoc.to_markdown_bytes(data, format=document_format)
    if not isinstance(text, str):
        raise TypeError("Markdown converter returned no text content")
    return text


def _html_to_markdown(html: str) -> str:
    from markdownify import ATX, markdownify

    # Markitdown's HTML converter selects ATX headings over markdownify's default.
    return markdownify(html, heading_style=ATX).strip()


def _main_page_content(data: bytes) -> bytes:
    """Keeps the main page content and drops chrome, hidden, and scripted elements."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(data, "html.parser")
    root = soup.find("main") or soup.body or soup
    removable = root.find_all(_PAGE_BOILERPLATE_TAGS)
    removable += root.find_all(
        role=lambda value: bool(value) and value.lower() in _PAGE_BOILERPLATE_ROLES
    )
    removable += root.find_all(attrs={"aria-hidden": "true"})
    for tag in removable:
        if not tag.decomposed:
            tag.decompose()
    return str(root).encode("utf-8")
