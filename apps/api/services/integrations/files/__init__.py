# apps/api/services/integrations/files/__init__.py

"""Published workspace File operations for integration providers."""

from services.agents.runtime.entity_references.domain import FileReference
from services.storage.errors import StorageNotFoundError, StoragePreconditionError

from .read_file_source import read_file_source
from .read_pinned_file_source import read_pinned_file_source
from .resolve_workspace_file_source import resolve_workspace_file_source
from .revision_stream import RevisionStream
from .stream_file_source import stream_file_source
from .utils import (
    pinned_files,
    require_pinned_file,
    source_changed_error,
    source_unavailable_error,
)

__all__ = [
    "FileReference",
    "RevisionStream",
    "StorageNotFoundError",
    "StoragePreconditionError",
    "pinned_files",
    "read_file_source",
    "read_pinned_file_source",
    "require_pinned_file",
    "resolve_workspace_file_source",
    "source_changed_error",
    "source_unavailable_error",
    "stream_file_source",
]
