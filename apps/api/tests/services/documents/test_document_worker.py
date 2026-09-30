"""Document worker process isolation, limits, and XML entity handling."""

import asyncio
import os
import sys
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from services.documents.precheck import PackageLimits
from services.documents.worker import (
    DocumentRejectedError,
    DocumentWorkerError,
    DocumentWorkerPool,
)
from tests.support.office_documents import (
    MARKER,
    office_file,
    with_entity_expansion,
    with_external_entity,
)

_MIB = 1024 * 1024


def _pool(*, timeout_seconds: float = 30.0, memory_bytes: int = 1024 * _MIB) -> DocumentWorkerPool:
    return DocumentWorkerPool(
        workers=1,
        timeout_seconds=timeout_seconds,
        memory_bytes=memory_bytes,
        max_source_bytes=10 * _MIB,
        limits=PackageLimits(
            max_entries=100, max_uncompressed_bytes=50 * _MIB, max_compression_ratio=100
        ),
        handlers="tests.support.document_worker_probes",
    )


@pytest_asyncio.fixture
async def pool() -> AsyncIterator[DocumentWorkerPool]:
    worker_pool = _pool()
    yield worker_pool
    await worker_pool.close()


async def _pid(pool: DocumentWorkerPool) -> int:
    return (await pool.run("pid", document_format="docx", data=b"")).value["pid"]


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.parametrize("document_format", ["pptx", "xlsx", "docx"])
async def test_entities_never_expand(
    pool: DocumentWorkerPool, document_format: str, tmp_path
) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("host secret")
    clean = await pool.run(
        "describe", document_format=document_format, data=office_file(document_format)
    )
    assert MARKER in clean.value["text"]

    for hostile in (
        with_entity_expansion(document_format),
        with_external_entity(document_format, str(secret)),
    ):
        try:
            result = await pool.run("describe", document_format=document_format, data=hostile)
        except DocumentRejectedError:
            continue
        assert "lol" not in result.value["text"]
        assert "host secret" not in result.value["text"]


async def test_timeout_kills_worker_and_next_call_gets_a_fresh_one() -> None:
    pool = _pool(timeout_seconds=2.0)
    try:
        first_pid = await _pid(pool)
        with pytest.raises(DocumentWorkerError):
            await pool.run("sleep", document_format="docx", data=b"")
        assert await _pid(pool) != first_pid
        assert not _is_running(first_pid)
    finally:
        await pool.close()


@pytest.mark.skipif(sys.platform == "darwin", reason="macOS doesn't enforce RLIMIT_AS")
async def test_memory_limit_kills_worker_and_next_call_gets_a_fresh_one() -> None:
    pool = _pool(memory_bytes=512 * _MIB)
    try:
        first_pid = await _pid(pool)
        with pytest.raises(DocumentWorkerError):
            await pool.run(
                "allocate", document_format="docx", data=b"", args={"bytes": 1024 * _MIB}
            )
        assert await _pid(pool) != first_pid
        assert not _is_running(first_pid)
    finally:
        await pool.close()


async def test_cancelled_calls_leave_other_workers_and_next_call_gets_a_fresh_one(
    pool: DocumentWorkerPool,
) -> None:
    first_pid = await _pid(pool)
    active = asyncio.create_task(pool.run("sleep", document_format="docx", data=b""))
    await asyncio.sleep(0)
    queued = asyncio.create_task(_pid(pool))
    await asyncio.sleep(0)

    queued.cancel()
    with pytest.raises(asyncio.CancelledError):
        await queued
    assert _is_running(first_pid)
    assert not active.done()

    active.cancel()
    with pytest.raises(asyncio.CancelledError):
        await active
    assert await _pid(pool) != first_pid
    assert not _is_running(first_pid)


async def test_close_stops_a_worker_that_was_still_starting(monkeypatch) -> None:
    pool = _pool()
    create_subprocess_exec = asyncio.create_subprocess_exec
    started, release = asyncio.Event(), asyncio.Event()
    processes = []

    async def paused_start(*args, **kwargs):
        processes.append(await create_subprocess_exec(*args, **kwargs))
        started.set()
        await release.wait()
        return processes[0]

    monkeypatch.setattr(asyncio, "create_subprocess_exec", paused_start)
    call = asyncio.create_task(_pid(pool))
    await started.wait()
    await pool.close()
    release.set()

    with pytest.raises(DocumentWorkerError, match="shutting down"):
        await call
    assert processes[0].returncode is not None


@pytest.mark.parametrize("document_format", ["pptx", "xlsx", "docx"])
async def test_saved_output_reopens(pool: DocumentWorkerPool, document_format: str) -> None:
    saved = await pool.run(
        "round_trip", document_format=document_format, data=office_file(document_format)
    )
    assert saved.data is not None

    reopened = await pool.run("describe", document_format=document_format, data=saved.data)

    assert MARKER in reopened.value["text"]


async def test_saved_output_that_fails_the_precheck_is_refused(pool: DocumentWorkerPool) -> None:
    with pytest.raises(DocumentRejectedError, match="parts"):
        await pool.run(
            "round_trip",
            document_format="xlsx",
            data=office_file("xlsx"),
            args={"output_limits": {"max_entries": 1}},
        )


async def test_worker_environment_has_no_application_secrets(
    pool: DocumentWorkerPool, monkeypatch
) -> None:
    monkeypatch.setenv("PRAXIS_PARENT_SECRET", "do-not-inherit")

    result = await pool.run("environment", document_format="docx", data=b"")

    assert "PRAXIS_PARENT_SECRET" not in result.value["keys"]
    assert "SECRET_KEY" not in result.value["keys"]
    assert result.value["settings_loaded"] is False
