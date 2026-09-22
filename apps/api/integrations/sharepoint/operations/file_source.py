# apps/api/integrations/sharepoint/operations/file_source.py

"""Loads reviewed workspace File revisions for SharePoint uploads."""

from dataclasses import dataclass

from core.exceptions.general import AppValidationError, NotFoundError
from models.files import File, FileRevision
from services.files.contract import require_matching_pair
from services.integrations.files import (
    StorageNotFoundError,
    StoragePreconditionError,
    read_file_source,
    resolve_workspace_file_source,
)

from ..settings import sharepoint_settings
from .utils import file_error


@dataclass(frozen=True)
class FileSource:
    file: File
    revision: FileRevision
    data: bytes = b""

    def approval_details(self) -> dict:
        return {
            "file_id": str(self.file.id),
            "revision_id": str(self.revision.id),
            "content_hash": self.revision.content_hash,
            "name": self.file.name,
            "content_type": self.revision.content_type,
            "size_bytes": self.revision.size_bytes,
        }


async def resolve_file_source(db, *, workspace, reference) -> FileSource:
    try:
        file, revision = await resolve_workspace_file_source(
            db, workspace_id=workspace.id, file_id=reference.entity_id
        )
    except NotFoundError:
        raise file_error(
            "Choose an available File in this workspace.",
            "source_unavailable",
            operation="file_source",
        ) from None
    try:
        require_matching_pair(revision.content_type, revision.extension)
    except AppValidationError:
        raise file_error(
            "Choose a supported File type.", "unsupported_type", operation="file_source"
        ) from None
    if revision.size_bytes == 0:
        raise file_error(
            "Choose a File with non-empty content.", "empty_content", operation="file_source"
        )
    if revision.size_bytes > sharepoint_settings.SHAREPOINT_FILE_MAX_UPLOAD_BYTES:
        raise file_error(
            "This File exceeds the SharePoint upload limit.", "too_large", operation="file_source"
        )
    return FileSource(file, revision)


async def load_file_source(db, *, workspace, reference, pinned) -> FileSource:
    source = await resolve_file_source(db, workspace=workspace, reference=reference)
    details = source.approval_details()
    if not isinstance(pinned, dict) or any(
        pinned.get(key) != details[key] for key in ("file_id", "revision_id", "content_hash")
    ):
        raise file_error(
            "The source File changed after review. Prepare it for approval again.",
            "source_changed",
            operation="file_source",
        )
    try:
        data = await read_file_source(source.revision)
    except StorageNotFoundError:
        raise file_error(
            "The source File content is unavailable. Choose another File or upload it again.",
            "source_unavailable",
            operation="file_source",
        ) from None
    except StoragePreconditionError:
        raise file_error(
            "The source File no longer matches the reviewed revision. Prepare it again.",
            "source_changed",
            operation="file_source",
        ) from None
    return FileSource(source.file, source.revision, data)
