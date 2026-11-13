# apps/api/services/integrations/files/revision_stream.py

"""Reads a File revision in caller-sized pieces for chunked provider uploads."""

from collections.abc import AsyncGenerator

from models.files import FileRevision
from services.storage.errors import StorageNotFoundError, StoragePreconditionError

from .stream_file_source import stream_file_source
from .utils import source_changed_error, source_unavailable_error


class RevisionStream:
    """Reads a revision in caller-sized pieces, so a large video never sits in memory whole.

    `verify` must pass before the upload is published, because a changed File is only
    detected once every byte has been read. Use it as an async context manager so storage
    is released when the upload stops early.
    """

    def __init__(self, revision: FileRevision, *, provider_key: str, operation: str) -> None:
        self._revision = revision
        self._seam = {"provider_key": provider_key, "operation": operation}
        self._chunks: AsyncGenerator[bytes] | None = None
        self._buffer = bytearray()

    async def __aenter__(self) -> "RevisionStream":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._chunks is not None:
            await self._chunks.aclose()

    @property
    def size(self) -> int:
        return self._revision.size_bytes

    async def read(self, size: int) -> bytes:
        """Returns exactly `size` bytes, or fails when the stored content is shorter."""
        while len(self._buffer) < size:
            chunk = await self._next_chunk()
            if chunk is None:
                raise source_changed_error(**self._seam)
            self._buffer.extend(chunk)
        data = bytes(self._buffer[:size])
        del self._buffer[:size]
        return data

    async def verify(self) -> None:
        """Fails unless every stored byte was read and they match the revision's hash."""
        if self._buffer or await self._next_chunk() is not None:
            raise source_changed_error(**self._seam)

    async def _next_chunk(self) -> bytes | None:
        if self._chunks is None:
            self._chunks = stream_file_source(self._revision)
        try:
            return await anext(self._chunks)
        except StopAsyncIteration:
            return None
        except StorageNotFoundError:
            raise source_unavailable_error(**self._seam) from None
        except StoragePreconditionError:
            raise source_changed_error(**self._seam) from None
