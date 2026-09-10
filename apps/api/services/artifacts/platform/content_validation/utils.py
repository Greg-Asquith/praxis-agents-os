# apps/api/services/artifacts/platform/content_validation/utils.py

"""Checks declared dependencies without resolving or fetching content."""

import re
from html import unescape
from html.parser import HTMLParser
from typing import NoReturn
from urllib.parse import unquote

from markdown_it import MarkdownIt

from core.exceptions.general import AppValidationError

_ESCAPE = re.compile(r"\\(?:u([0-9a-f]{4})|x([0-9a-f]{2})|([0-9a-f]{1,6})\s?|(.))", re.I)
_PRIVATE_PATH = re.compile(r"(?:^|[/\s'\"])(?:workspaces/|files[/?]|artifacts/)", re.I)
_INLINE_DATA = re.compile(
    r"data:(?:image/(?:png|jpeg|gif|webp|avif)|font/(?:woff2?|ttf|otf));base64,[a-z0-9+/=\s]+\Z",
    re.I,
)
_CSS_URL = re.compile(r"\burl\s*+\(", re.I)
_CSS_ESCAPE = re.compile(r"\\(?:([0-9a-f]{1,6})(?:\r\n|[\t\n\f\r ])?|(\r\n|[\s\S]))", re.I)
_MERMAID_IMAGE = re.compile(r"\bimg\s*:\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s,}]+))", re.I)
_URL_ATTRIBUTES = frozenset(
    {"src", "href", "xlink:href", "poster", "data", "action", "formaction", "background"}
)


def _decode_escape(match: re.Match[str]) -> str:
    for value in match.groups()[:3]:
        if value is not None:
            codepoint = int(value, 16)
            return chr(codepoint) if 0 < codepoint <= 0x10FFFF else "\ufffd"
    return match.group(4)


def _normalise(content: str) -> str:
    # Bound decoding work and refuse deeper encodings rather than leaving them unchecked.
    for _ in range(8):
        decoded = _ESCAPE.sub(_decode_escape, unquote(unescape(content)))
        if decoded == content:
            return decoded
        content = decoded
    return _reject_dependency()


def _reject_dependency() -> NoReturn:
    raise AppValidationError(
        "Platform artifacts must contain their assets. Remove linked resources and embed images "
        "or fonts before publishing.",
        field="content",
    )


def _validate_reference(value: str) -> None:
    value = value.strip()
    if value and not value.startswith("#") and not _INLINE_DATA.fullmatch(value):
        _reject_dependency()


def _strip_css_comments(content: str) -> str:
    pieces = []
    cursor = 0
    while (start := content.find("/*", cursor)) != -1:
        pieces.append(content[cursor:start])
        end = content.find("*/", start + 2)
        if end == -1:
            _reject_dependency()
        cursor = end + 2
    pieces.append(content[cursor:])
    return "".join(pieces)


def _decode_css_escape(match: re.Match[str]) -> str:
    if match.group(1) is not None:
        codepoint = int(match.group(1), 16)
        return chr(codepoint) if 0 < codepoint <= 0x10FFFF else "\ufffd"
    value = match.group(2)
    return "" if value in {"\r\n", "\n", "\f", "\r"} else value


def _validate_css(content: str) -> None:
    content = _CSS_ESCAPE.sub(_decode_css_escape, _strip_css_comments(content))
    # Imports and image-set string sources can introduce dependencies without url().
    if re.search(r"@import\b|\b(?:-webkit-)?image-set\s*\(", content, re.I):
        _reject_dependency()
    cursor = 0
    while match := _CSS_URL.search(content, cursor):
        end = content.find(")", match.end())
        if end == -1:
            _reject_dependency()
        value = content[match.end() : end].strip()
        if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
            value = value[1:-1]
        _validate_reference(value)
        cursor = end + 1


class _DependencyParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._style_chunks: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if value is None:
                continue
            if name in _URL_ATTRIBUTES:
                _validate_reference(value)
            elif name in {"srcset", "imagesrcset", "srcdoc", "ping"} and value.strip():
                # Alternate source lists and nested documents need a separate review.
                _reject_dependency()
            elif name == "style":
                _validate_css(value)
        if tag in {"base", "iframe", "object", "embed"}:
            _reject_dependency()
        if tag == "meta" and any(
            name == "http-equiv" and (value or "").lower() == "refresh" for name, value in attrs
        ):
            _reject_dependency()
        if tag == "style":
            self._style_chunks = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # HTML keeps these style elements open, unlike HTMLParser.
        if tag == "style":
            _reject_dependency()
        super().handle_startendtag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if self._style_chunks is not None:
            self._style_chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "style" and self._style_chunks is not None:
            _validate_css("".join(self._style_chunks))
            self._style_chunks = None

    def close(self) -> None:
        super().close()
        self.handle_endtag("style")


def _render_markdown_for_validation(content: str) -> str:
    parser = MarkdownIt("commonmark").enable("table")
    # Retain every destination for the dependency check, including unsafe schemes.
    parser.validateLink = lambda _value: True
    tokens = parser.parse(content)
    pending = list(tokens)
    while pending:
        token = pending.pop()
        # The parser omits content beyond its nesting limit.
        if token.level >= parser.options.maxNesting - 1:
            _reject_dependency()
        pending.extend(token.children or [])
    return parser.renderer.render(tokens, parser.options, {})


def validate_platform_content(*, artifact_type: str, content: str) -> None:
    """Rejects declared asset dependencies; the serving CSP still confines inline scripts."""
    if artifact_type == "csv":
        return
    parser = _DependencyParser()
    parsed_content = (
        _render_markdown_for_validation(content) if artifact_type == "markdown" else content
    )
    parser.feed(parsed_content)
    parser.close()
    if artifact_type == "mermaid":
        for match in _MERMAID_IMAGE.finditer(content):
            _validate_reference(next(value for value in match.groups() if value is not None))
        if re.search(r"^\s*click\s", content, re.M | re.I):
            _reject_dependency()
    if _PRIVATE_PATH.search(_normalise(content)):
        _reject_dependency()
