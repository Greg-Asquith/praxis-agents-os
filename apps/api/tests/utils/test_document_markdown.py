"""Unit coverage for the shared document-to-markdown converter."""

import pytest

from tests.support.documents import tiny_docx, tiny_pdf
from utils.document_markdown import DocumentConversionError, convert_document_to_markdown


async def test_convert_document_to_markdown_converts_html_directly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_binary_conversion(_data: bytes, _extension: str) -> str:
        raise AssertionError("HTML conversion must not use the binary converter")

    monkeypatch.setattr(
        "utils.document_markdown._convert_sync",
        unexpected_binary_conversion,
    )
    markdown = await convert_document_to_markdown(
        b"<h1>Guide</h1><ul><li>First</li><li>Second</li></ul>",
        content_type="text/html",
        filename="guide",
        max_bytes=1_000,
    )

    assert markdown == "# Guide\n\n* First\n* Second"


@pytest.mark.parametrize(
    ("data", "content_type", "filename", "markers"),
    [
        (tiny_pdf("PDF marker"), "application/pdf", "report.pdf", ("PDF marker",)),
    ],
)
async def test_convert_document_to_markdown_converts_supported_binary_formats(
    data: bytes,
    content_type: str,
    filename: str,
    markers: tuple[str, ...],
) -> None:
    markdown = await convert_document_to_markdown(
        data,
        content_type=content_type,
        filename=filename,
        max_bytes=100_000,
    )

    assert all(marker in markdown for marker in markers)


async def test_convert_document_to_markdown_maps_corrupt_input_error() -> None:
    with pytest.raises(DocumentConversionError, match="Document could not be converted"):
        await convert_document_to_markdown(
            b"not a document",
            content_type="application/pdf",
            filename="broken.pdf",
            max_bytes=100_000,
        )


async def test_convert_document_to_markdown_sniffs_bytes_without_extension_hint() -> None:
    markdown = await convert_document_to_markdown(
        tiny_docx(),
        content_type="application/octet-stream",
        filename="report",
        max_bytes=100_000,
    )

    assert "Quarterly Results" in markdown


@pytest.mark.parametrize(
    "content_type,expected",
    [
        ("image/png", None),
        ("TEXT/PLAIN; charset=utf-8", None),
        (" TEXT/PLAIN ", "text/plain"),
        ("Application/PDF", "application/pdf"),
    ],
)
def test_document_content_type_uses_supported_document_contract(content_type, expected):
    from utils.document_markdown import document_content_type

    assert document_content_type(content_type) == expected


@pytest.mark.parametrize("max_bytes", [0, 56, 64 * 1024])
async def test_bounding_metadata_and_string_api_respect_all_byte_caps(max_bytes):
    from utils.document_markdown import convert_document_to_markdown_result, truncate_markdown

    text = "界" * 30_000
    result = await convert_document_to_markdown_result(
        text.encode(), content_type="text/plain", filename="document", max_bytes=max_bytes
    )
    assert result.truncated is True
    assert len(result.markdown.encode()) <= max_bytes
    assert "�" not in result.markdown
    assert truncate_markdown(text, max_bytes=max_bytes) == result.markdown
