"""Conversion deadlines kill the worker instead of leaving a parser running."""

import asyncio
import os

import pytest

from tests.support.document_conversion_worker import slow_conversion
from utils.document_markdown import DocumentConversionError, convert_document_to_markdown


@pytest.mark.parametrize("cancel", [False, True])
async def test_conversion_timeout_and_cancellation_kill_worker(monkeypatch, tmp_path, cancel):
    started = tmp_path / "worker.pid"
    monkeypatch.setattr("utils.document_markdown._convert_bounded_sync", slow_conversion)
    task = asyncio.create_task(
        convert_document_to_markdown(
            str(started).encode(),
            content_type="text/plain",
            filename="probe.txt",
            max_bytes=100,
            timeout_seconds=5,
        )
    )
    async with asyncio.timeout(4):
        while not started.exists():  # noqa: ASYNC110 - A separate process publishes the PID.
            await asyncio.sleep(0.01)
    pid = int(started.read_text())
    if cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else DocumentConversionError):
        await task
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.mark.parametrize(
    "content_type",
    [
        "text/plain",
        "text/markdown",
        "text/csv",
        "application/json",
        "text/html",
        "application/xhtml+xml",
    ],
)
async def test_strict_utf8_rejection_and_default_replacement_in_real_worker(content_type):
    with pytest.raises(DocumentConversionError, match="could not be converted"):
        await convert_document_to_markdown(
            b"\xff",
            content_type=content_type,
            filename="document",
            max_bytes=100,
            timeout_seconds=5,
            strict_utf8=True,
        )
    assert (
        await convert_document_to_markdown(
            b"\xff",
            content_type=content_type,
            filename="document",
            max_bytes=100,
            timeout_seconds=5,
        )
        == "�"
    )


@pytest.mark.parametrize(
    "content_type,source", [("text/plain", "text"), ("text/html", "converted")]
)
async def test_real_worker_decodes_text_once(content_type, source):
    from tests.support.document_conversion_worker import WorkerDecodedBytes
    from utils.document_markdown import convert_document_to_markdown_result

    result = await convert_document_to_markdown_result(
        WorkerDecodedBytes(b"guide"),
        content_type=content_type,
        filename="document",
        max_bytes=100,
        timeout_seconds=5,
        strict_utf8=True,
    )
    assert result.markdown == "guide"
    assert result.source == source
    assert result.truncated is False
