# apps/api/services/integrations/files/read_pinned_file_source.py

"""Reads a pinned File revision whole, reporting storage failures as provider errors."""

from models.files import FileRevision
from services.storage.errors import StorageNotFoundError, StoragePreconditionError

from .read_file_source import read_file_source
from .utils import source_changed_error, source_unavailable_error


async def read_pinned_file_source(
    revision: FileRevision, *, provider_key: str, operation: str
) -> bytes:
    """Reads a revision, verifying its size and SHA-256; fails when it's missing or changed."""
    try:
        return await read_file_source(revision)
    except StorageNotFoundError:
        raise source_unavailable_error(provider_key=provider_key, operation=operation) from None
    except StoragePreconditionError:
        raise source_changed_error(provider_key=provider_key, operation=operation) from None
