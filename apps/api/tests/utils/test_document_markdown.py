"""Unit coverage for the shared document-to-markdown converter."""

import pytest

from tests.support.documents import tiny_docx, tiny_pdf, tiny_pptx, tiny_xlsx
from utils.document_markdown import DocumentConversionError, convert_document_to_markdown


@pytest.mark.parametrize("content_type", ["text/html", "application/xhtml+xml"])
async def test_convert_document_to_markdown_converts_html_directly(
    content_type: str,
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


@pytest.mark.parametrize(
    ("data", "content_type", "filename", "markers"),
    [
        (tiny_pdf("PDF marker"), "application/pdf", "report.pdf", ("PDF marker",)),
        (
            tiny_docx(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "report.docx",
            ("Quarterly Results", "North", "1250"),
        ),
        (
            tiny_pptx(),
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "review.pptx",
            ("Launch Review", "Ship pilot"),
        ),
        (
            tiny_xlsx(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "results.xlsx",
            ("Summary", "Revenue", "Regions", "North"),
        ),
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


async def test_convert_document_to_markdown_maps_blank_pdf_error() -> None:
    with pytest.raises(DocumentConversionError, match="Document could not be converted"):
        await convert_document_to_markdown(
            tiny_pdf(None),
            content_type="application/pdf",
            filename="scan.pdf",
            max_bytes=100_000,
        )
