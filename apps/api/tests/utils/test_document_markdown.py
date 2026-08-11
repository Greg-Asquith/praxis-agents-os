# apps/api/tests/utils/test_document_markdown.py

"""Unit coverage for the shared document-to-markdown converter."""

import sys
from types import SimpleNamespace

import pytest

from utils.document_markdown import (
    DocumentConversionError,
    convert_document_to_markdown,
)


@pytest.mark.parametrize("content_type", ["text/html", "application/xhtml+xml"])
async def test_convert_document_to_markdown_converts_html_directly(
    content_type: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnexpectedMarkItDown:
        def __init__(self) -> None:
            raise AssertionError("HTML conversion must not import Markitdown")

    monkeypatch.setitem(
        sys.modules,
        "markitdown",
        SimpleNamespace(MarkItDown=UnexpectedMarkItDown),
    )

    markdown = await convert_document_to_markdown(
        b"<h1>Guide</h1><ul><li>First</li><li>Second</li></ul>",
        content_type=content_type,
        filename="guide",
        max_bytes=1_000,
    )

    assert markdown == "# Guide\n\n* First\n* Second"


async def test_convert_document_to_markdown_wraps_html_conversion_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_conversion(_data: bytes) -> str:
        raise ValueError("invalid HTML")

    monkeypatch.setattr(
        "utils.document_markdown._convert_html_sync",
        fail_conversion,
    )

    with pytest.raises(DocumentConversionError, match="could not be converted"):
        await convert_document_to_markdown(
            b"<h1>Guide</h1>",
            content_type="text/html",
            filename="guide.html",
            max_bytes=1_000,
        )
