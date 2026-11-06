# apps/api/tests/utils/test_document_conversion_process.py

"""Document conversion runs in the limited worker, never in the calling process."""

import sys

import pytest

from services.documents.precheck import PackageLimits
from services.documents.worker import DocumentWorkerPool
from tests.support.documents import tiny_docx
from tests.support.office_documents import rewrite_package
from utils.document_markdown import (
    DocumentConversionError,
    convert_document_to_markdown,
    find_document_text,
    read_document_window,
)
from utils.text_window import TextWindowError

_MIB = 1024 * 1024


async def test_conversion_parses_outside_the_calling_process(monkeypatch) -> None:
    def parse_in_parent(*_args, **_kwargs):
        raise AssertionError("The document was parsed in the calling process")

    monkeypatch.setattr("anydoc.to_markdown_bytes", parse_in_parent)

    markdown = await convert_document_to_markdown(
        tiny_docx(), content_type="application/octet-stream", filename="report", max_bytes=1_000
    )

    assert "Quarterly Results" in markdown


async def test_office_files_that_fail_the_package_precheck_are_not_converted() -> None:
    with_macros = rewrite_package(
        tiny_docx(), lambda _name, content: content, {"word/vbaProject.bin": b"macro"}
    )

    with pytest.raises(DocumentConversionError):
        await convert_document_to_markdown(
            with_macros,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            filename="report.docx",
            max_bytes=1_000,
        )


@pytest.mark.skipif(sys.platform == "darwin", reason="macOS doesn't enforce RLIMIT_AS")
async def test_conversion_over_the_memory_limit_fails_without_the_parent(monkeypatch) -> None:
    pool = DocumentWorkerPool(
        workers=1,
        timeout_seconds=30,
        memory_bytes=512 * _MIB,
        max_source_bytes=_MIB,
        limits=PackageLimits(max_entries=10, max_uncompressed_bytes=_MIB, max_compression_ratio=10),
        handlers="tests.support.document_conversion_worker",
    )
    monkeypatch.setattr("utils.document_markdown.get_document_worker_pool", lambda: pool)
    try:
        with pytest.raises(DocumentConversionError):
            await convert_document_to_markdown(
                b"guide", content_type="text/plain", filename="guide.txt", max_bytes=100
            )
    finally:
        await pool.close()


@pytest.mark.parametrize("content_type", ["text/plain", "text/html"])
async def test_strict_utf8_rejects_and_default_replaces_invalid_bytes(content_type):
    with pytest.raises(DocumentConversionError, match="could not be converted"):
        await convert_document_to_markdown(
            b"\xff",
            content_type=content_type,
            filename="document",
            max_bytes=100,
            strict_utf8=True,
        )
    assert (
        await convert_document_to_markdown(
            b"\xff", content_type=content_type, filename="document", max_bytes=100
        )
        == "�"
    )


@pytest.mark.parametrize(
    ("operation", "content_type"), [("read", "text/plain"), ("find", "text/html")]
)
async def test_whole_document_reads_return_bounded_results_and_reject_invalid_utf8(
    operation, content_type
):
    function, arguments = (
        (read_document_window, {"offset": 0, "max_bytes": 4})
        if operation == "read"
        else (find_document_text, {"query": "guide", "limit": 1})
    )
    result = await function(
        b"guide" * 20_000, content_type=content_type, filename="document", **arguments
    )
    if operation == "read":
        assert result.window.content == "guid" and result.window.total_bytes == 100_000
    else:
        assert len(result.matches) == 1 and result.has_more
        assert len(result.matches[0][1]) <= 245 and result.total_bytes == 100_000
    with pytest.raises(DocumentConversionError):
        await function(b"\xff", content_type=content_type, filename="document", **arguments)


async def test_window_offset_past_the_content_reports_the_converted_size() -> None:
    with pytest.raises(TextWindowError, match="contains 5 bytes"):
        await read_document_window(
            b"guide", content_type="text/plain", filename="guide.txt", offset=10, max_bytes=4
        )
