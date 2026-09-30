# apps/api/services/documents/worker.py

"""Process-local pool of document worker processes.

Each worker is a separate Python process started with a minimal environment
and address-space and CPU limits. A call that times out, is cancelled, or
kills its worker discards that process, so the next call gets a fresh one.
"""

from __future__ import annotations

import asyncio
import json
import math
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from core.exceptions.general import AppValidationError
from core.settings import settings
from services.documents.precheck import OFFICE_FORMATS, PackageLimits
from services.documents.worker_process import FRAME_PREFIX

_API_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_HANDLERS = "services.documents.handlers"
_WORKER_ENV = {"LC_ALL": "C.UTF-8", "OPENPYXL_DEFUSEDXML": "True"}
_MAX_RESULT_HEADER_BYTES = 16 * 1024 * 1024
_MAX_REJECTION_MESSAGE_CHARS = 300
# Plain-text formats that only the table read accepts.
TABLE_FORMATS = frozenset({"csv", "tsv", "json"})


class DocumentRejectedError(AppValidationError):
    """The Office file was refused or couldn't be opened."""


class DocumentRequestError(AppValidationError):
    """The request names a sheet, range, or part the file doesn't have."""


class DocumentWorkerError(AppValidationError):
    """The document worker stopped before it finished the call."""


@dataclass(frozen=True)
class DocumentWorkerResult:
    value: dict[str, Any]
    data: bytes | None


class _WorkerProcess:
    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self.process = process

    @property
    def pid(self) -> int:
        return self.process.pid

    async def call(
        self, header: dict[str, Any], payload: bytes, max_payload_bytes: int
    ) -> tuple[dict[str, Any], bytes]:
        stdin, stdout = self.process.stdin, self.process.stdout
        if stdin is None or stdout is None:
            raise DocumentWorkerError("The document worker has no open pipes.")
        encoded = json.dumps(header).encode()
        stdin.write(FRAME_PREFIX.pack(len(encoded), len(payload)) + encoded + payload)
        await stdin.drain()
        header_size, payload_size = FRAME_PREFIX.unpack(await stdout.readexactly(FRAME_PREFIX.size))
        if header_size > _MAX_RESULT_HEADER_BYTES or payload_size > max_payload_bytes:
            raise DocumentWorkerError("The document result was larger than allowed.")
        response = json.loads(await stdout.readexactly(header_size))
        return response, await stdout.readexactly(payload_size)

    def kill(self) -> None:
        if self.process.returncode is None:
            self.process.kill()

    async def stop(self) -> None:
        self.kill()
        await self.process.wait()


class DocumentWorkerPool:
    """Own the document worker processes for one application process."""

    def __init__(
        self,
        *,
        workers: int,
        timeout_seconds: float,
        memory_bytes: int,
        max_source_bytes: int,
        limits: PackageLimits,
        handlers: str = _DEFAULT_HANDLERS,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_source_bytes = max_source_bytes
        self._config = json.dumps(
            {
                "handlers": handlers,
                "memory_bytes": memory_bytes,
                "cpu_seconds": math.ceil(timeout_seconds) + 1,
                "limits": asdict(limits),
            }
        )
        self._slots = asyncio.Semaphore(workers)
        self._idle: list[_WorkerProcess] = []
        self._live: set[_WorkerProcess] = set()
        self._closed = False

    @classmethod
    def from_settings(cls) -> DocumentWorkerPool:
        return cls(
            workers=settings.DOCUMENT_TOOLS_WORKERS,
            timeout_seconds=settings.DOCUMENT_TOOLS_TIMEOUT_SECONDS,
            memory_bytes=settings.DOCUMENT_TOOLS_WORKER_MEMORY_BYTES,
            max_source_bytes=settings.DOCUMENT_TOOLS_MAX_SOURCE_BYTES,
            limits=PackageLimits(
                max_entries=settings.DOCUMENT_TOOLS_MAX_ZIP_ENTRIES,
                max_uncompressed_bytes=settings.DOCUMENT_TOOLS_MAX_UNCOMPRESSED_BYTES,
                max_compression_ratio=settings.DOCUMENT_TOOLS_MAX_COMPRESSION_RATIO,
            ),
        )

    async def run(
        self,
        operation: str,
        *,
        document_format: str,
        data: bytes,
        args: dict[str, Any] | None = None,
        attachments: Sequence[bytes] = (),
    ) -> DocumentWorkerResult:
        """Runs one operation in a worker and returns its JSON result and output bytes.

        Attachments, such as images an edit adds, travel after the file bytes.
        """
        if document_format not in OFFICE_FORMATS | TABLE_FORMATS:
            raise DocumentRejectedError("Only .pptx, .xlsx, .docx, and table files are supported.")
        if len(data) + sum(len(item) for item in attachments) > self._max_source_bytes:
            raise DocumentRejectedError("The file is larger than document tools allow.")
        request_args = dict(args or {})
        if attachments:
            request_args["attachment_sizes"] = [len(item) for item in attachments]
        header = {"operation": operation, "format": document_format, "args": request_args}
        await self._admit()
        try:
            response, payload = await self._call(header, b"".join([data, *attachments]))
        finally:
            self._slots.release()
        return _result(response, payload, document_format)

    async def _admit(self) -> None:
        # Waiting for a free worker has its own timeout, so processing still gets the full limit.
        try:
            async with asyncio.timeout(self._timeout_seconds):
                await self._slots.acquire()
        except TimeoutError:
            raise DocumentWorkerError("Document processing is busy. Try again shortly.") from None

    async def _call(self, header: dict[str, Any], data: bytes) -> tuple[dict[str, Any], bytes]:
        worker: _WorkerProcess | None = None
        try:
            async with asyncio.timeout(self._timeout_seconds):
                worker = await self._checkout()
                response = await worker.call(header, data, self._max_source_bytes)
        except BaseException as exc:
            if worker is not None:
                self._discard(worker)
            if isinstance(exc, TimeoutError | asyncio.IncompleteReadError | ConnectionError):
                raise DocumentWorkerError(
                    "Processing the document stopped because it passed the time or memory limit."
                ) from None
            raise
        if self._closed:
            self._discard(worker)
        else:
            self._idle.append(worker)
        return response

    async def _checkout(self) -> _WorkerProcess:
        if self._closed:
            raise _shutting_down()
        if self._idle:
            return self._idle.pop()
        return await self._spawn()

    async def _spawn(self) -> _WorkerProcess:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-E",
            "-s",
            "-B",
            "-m",
            "services.documents.worker_process",
            self._config,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            cwd=_API_ROOT,
            env=_WORKER_ENV,
        )
        worker = _WorkerProcess(process)
        if self._closed:
            # close() ran while this process was starting, so it never saw it.
            await worker.stop()
            raise _shutting_down()
        self._live.add(worker)
        return worker

    def _discard(self, worker: _WorkerProcess) -> None:
        worker.kill()
        self._live.discard(worker)

    async def close(self) -> None:
        """Stops every worker process, including any mid-call."""
        self._closed = True
        workers = list(self._live)
        self._idle.clear()
        self._live.clear()
        for worker in workers:
            await worker.stop()


def _shutting_down() -> DocumentWorkerError:
    return DocumentWorkerError("Document processing is shutting down.")


def _result(response: dict[str, Any], payload: bytes, document_format: str) -> DocumentWorkerResult:
    if response.get("ok") is True:
        return DocumentWorkerResult(response["result"], payload or None)
    error = response.get("error")
    message = str(response.get("message", ""))[:_MAX_REJECTION_MESSAGE_CHARS]
    if error == "rejected":
        raise DocumentRejectedError(message or "The file was refused.")
    if error == "request":
        raise DocumentRequestError(message or "The request doesn't match the file.")
    if error == "unreadable":
        raise DocumentRejectedError(f"The file couldn't be opened as a .{document_format} file.")
    raise DocumentWorkerError("The document worker couldn't run the requested operation.")


_default_pool: DocumentWorkerPool | None = None


def get_document_worker_pool() -> DocumentWorkerPool:
    """Return the process-wide pool, creating it on first use."""
    global _default_pool
    if _default_pool is None:
        _default_pool = DocumentWorkerPool.from_settings()
    return _default_pool


async def close_document_worker_pool() -> None:
    """Close and discard the process-wide pool."""
    global _default_pool
    pool, _default_pool = _default_pool, None
    if pool is not None:
        await pool.close()
