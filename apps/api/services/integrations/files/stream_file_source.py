# apps/api/services/integrations/files/stream_file_source.py

"""Streams verified bytes from a resolved File revision without holding it in memory."""

import hashlib
from collections.abc import AsyncIterator
from contextlib import aclosing

from models.files import FileRevision
from services.files.utils import file_revision_ref
from services.storage.errors import StoragePreconditionError
from services.storage.factory import get_storage_provider
from services.storage.utils import storage_object_not_found


async def stream_file_source(revision: FileRevision) -> AsyncIterator[bytes]:
    """Yields an authorised revision's bytes, then checks its declared size and SHA-256.

    The check runs after the last chunk, so callers must read to the end, and treat
    the bytes as unverified, before publishing anything built from them.
    """
    provider = get_storage_provider()
    ref = file_revision_ref(revision)
    stored = await provider.stat_object(ref)
    if stored is None:
        raise storage_object_not_found(provider, ref, operation="stream_file_source")
    if stored.size_bytes != revision.size_bytes:
        raise StoragePreconditionError("File source size changed", operation="stream_file_source")
    digest = hashlib.sha256()
    size = 0
    # Closing this generator early closes the provider's stream too, releasing storage.
    async with aclosing(provider.stream_object(ref)) as chunks:
        async for chunk in chunks:
            size += len(chunk)
            if size > revision.size_bytes:
                raise StoragePreconditionError(
                    "File source exceeds its declared size", operation="stream_file_source"
                )
            digest.update(chunk)
            yield chunk
    if size != revision.size_bytes or digest.hexdigest() != revision.content_hash:
        raise StoragePreconditionError(
            "File source content changed", operation="stream_file_source"
        )
