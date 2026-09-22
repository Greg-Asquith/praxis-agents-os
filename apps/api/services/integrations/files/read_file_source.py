# apps/api/services/integrations/files/read_file_source.py

"""Reads bounded, verified bytes from a resolved File revision."""

from models.files import FileRevision
from services.files.utils import file_revision_ref
from services.storage.factory import get_storage_provider
from services.storage.utils import read_copy_content


async def read_file_source(revision: FileRevision) -> bytes:
    """Reads an authorised revision and verifies its declared size and SHA-256."""
    return await read_copy_content(
        get_storage_provider(),
        file_revision_ref(revision),
        revision.size_bytes,
        revision.content_hash,
    )
