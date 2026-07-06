"""File model factories for tests."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from models.files import File, FileReference, FileRevision, FileUpload
from models.workspace import Workspace
from services.files.contract import FileCategory
from services.files.utils import revision_object_key


def build_file(
    *,
    workspace: Workspace,
    file_id: UUID | None = None,
    **overrides,
) -> File:
    """Build an unsaved logical file model."""
    defaults = {
        "id": file_id or uuid4(),
        "workspace_id": workspace.id,
        "name": "example.pdf",
        "category": FileCategory.INGESTIBLE_DOCUMENT.value,
        "content_type": "application/pdf",
        "extension": ".pdf",
        "size_bytes": 12,
        "content_hash": "a" * 64,
        "revision_count": 0,
        "processing_status": "ready",
        "processing_attempts": 0,
    }
    defaults.update(overrides)
    return File(**defaults)


def build_file_revision(
    file: File,
    *,
    revision_id: UUID | None = None,
    revision_number: int = 1,
    revision_kind: str = "create",
    created_by_user_id: UUID | None = None,
    created_by_agent_id: UUID | None = None,
    created_by_system: bool | None = None,
    **overrides,
) -> FileRevision:
    """Build an unsaved file revision model."""
    selected_revision_id = revision_id or uuid4()
    defaults = {
        "id": selected_revision_id,
        "file_id": file.id,
        "workspace_id": file.workspace_id,
        "revision_number": revision_number,
        "revision_kind": revision_kind,
        "content_type": file.content_type,
        "extension": file.extension,
        "size_bytes": file.size_bytes,
        "content_hash": file.content_hash,
        "object_key": revision_object_key(
            file.workspace_id,
            file.id,
            selected_revision_id,
            file.extension,
        ),
        "created_by_user_id": created_by_user_id,
        "created_by_agent_id": created_by_agent_id,
        "created_by_system": bool(created_by_system),
    }
    if created_by_user_id is None and created_by_agent_id is None and created_by_system is None:
        defaults["created_by_system"] = True
    defaults.update(overrides)
    return FileRevision(**defaults)


def build_file_reference(
    file: File,
    *,
    reference_id: UUID | None = None,
    target_type: str = "conversation",
    target_id: UUID | None = None,
    file_revision_id: UUID | None = None,
    created_by_user_id: UUID | None = None,
    **overrides,
) -> FileReference:
    """Build an unsaved file reference model."""
    defaults = {
        "id": reference_id or uuid4(),
        "file_id": file.id,
        "workspace_id": file.workspace_id,
        "target_type": target_type,
        "target_id": target_id or uuid4(),
        "file_revision_id": file_revision_id,
        "created_by_user_id": created_by_user_id,
    }
    defaults.update(overrides)
    return FileReference(**defaults)


def build_file_upload(
    *,
    workspace: Workspace,
    upload_id: UUID | None = None,
    file_id: UUID | None = None,
    revision_id: UUID | None = None,
    object_key: str | None = None,
    created_by_user_id: UUID | None = None,
    **overrides,
) -> FileUpload:
    """Build an unsaved file upload staging row."""
    selected_file_id = file_id or uuid4()
    selected_revision_id = revision_id or uuid4()
    defaults = {
        "id": upload_id or uuid4(),
        "workspace_id": workspace.id,
        "file_id": selected_file_id,
        "revision_id": selected_revision_id,
        "object_key": object_key
        or revision_object_key(workspace.id, selected_file_id, selected_revision_id, ".pdf"),
        "filename": "example.pdf",
        "content_type": "application/pdf",
        "declared_size_bytes": 12,
        "declared_content_hash": "a" * 64,
        "created_by_user_id": created_by_user_id or uuid4(),
        "expires_at": datetime.now(UTC) + timedelta(minutes=10),
    }
    defaults.update(overrides)
    return FileUpload(**defaults)
