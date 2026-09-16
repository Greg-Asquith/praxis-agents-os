"""Conversion deadlines kill the worker instead of leaving a parser running."""

import asyncio
import os

import pytest

from tests.support.document_conversion_worker import slow_conversion
from utils.document_markdown import (
    DocumentConversionError,
    convert_document_to_markdown,
    find_document_text,
    read_document_window,
)


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.parametrize("operation", ["convert", "read", "find"])
async def test_conversion_timeout_and_cancellation_kill_worker(
    monkeypatch, tmp_path, cancel, operation
):
    started = tmp_path / "worker.pid"
    function, worker, arguments = {
        "convert": (convert_document_to_markdown, "_convert_bounded_sync", {"max_bytes": 100}),
        "read": (read_document_window, "_read_window_sync", {"offset": 0, "max_bytes": 100}),
        "find": (find_document_text, "_find_text_sync", {"query": "notes", "limit": 10}),
    }[operation]
    monkeypatch.setattr(f"utils.document_markdown.{worker}", slow_conversion)
    task = asyncio.create_task(
        function(
            str(started).encode(),
            content_type="text/plain",
            filename="probe.txt",
            timeout_seconds=5,
            **arguments,
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


@pytest.mark.parametrize("operation", ["read", "find"])
@pytest.mark.parametrize("content_type", ["text/plain", "text/html"])
async def test_whole_document_worker_decodes_once_and_rejects_invalid_utf8(operation, content_type):
    from tests.support.document_conversion_worker import WorkerDecodedBytes

    function, arguments = (
        (read_document_window, {"offset": 0, "max_bytes": 4})
        if operation == "read"
        else (find_document_text, {"query": "guide", "limit": 1})
    )
    result = await function(
        WorkerDecodedBytes(b"guide" * 20_000),
        content_type=content_type,
        filename="document",
        timeout_seconds=5,
        **arguments,
    )
    if operation == "read":
        assert result.window.content == "guid" and result.window.total_bytes == 100_000
    else:
        assert len(result.matches) == 1 and result.has_more
        assert len(result.matches[0][1]) <= 245 and result.total_bytes == 100_000
    with pytest.raises(DocumentConversionError):
        await function(
            b"\xff", content_type=content_type, filename="document", timeout_seconds=5, **arguments
        )
