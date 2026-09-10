# apps/api/services/files/utils.py

"""Helpers specific to workspace file services."""

import logging
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.auth import AuthorizationError
from core.exceptions.general import AppValidationError, NotFoundError
from models.files import File, FileFolder, FileRevision, FileUpload
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.files.domain import FileRead, FileRevisionRead
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider
from services.storage.paths import safe_filename, validate_object_key
from services.storage.provider import StorageProvider
from services.workspaces.utils import EDITOR_ROLES, MANAGER_ROLES
from utils.content import ContentScope, can_manage_platform_content
from utils.digests import sha256_hex as sha256_hex, sha256_hex_stream as sha256_hex_stream

logger = logging.getLogger(__name__)


def parse_extraction_payload_ids(payload: dict[str, Any]) -> tuple[UUID | None, UUID | None]:
    """Reads the file and revision identifiers from an extraction job."""
    try:
        file_id = UUID(str(payload.get("file_id")))
        revision_id = UUID(str(payload.get("revision_id")))
    except (TypeError, ValueError, AttributeError):
        return None, None
    return file_id, revision_id


def normalize_required_text(value: str, *, field: str = "name", max_length: int = 255) -> str:
    """Trim required labels and enforce their persisted length."""
    normalized = value.strip()
    if not normalized:
        raise AppValidationError("Value cannot be blank", field=field)
    if len(normalized) > max_length:
        raise AppValidationError(f"Value cannot exceed {max_length} characters", field=field)
    return normalized


def normalize_extension(extension: str) -> str:
    normalized = extension.strip().lower()
    if not normalized.startswith("."):
        normalized = f".{normalized}"
    return normalized


def revision_object_key(
    workspace_id: UUID,
    file_id: UUID,
    revision_id: UUID,
    extension: str,
) -> str:
    """Build the private object key for a file revision."""
    key = f"workspaces/{workspace_id}/files/{file_id}/{revision_id}{normalize_extension(extension)}"
    make_storage_object_ref(StorageBucket.PRIVATE, key)
    return key


def revision_markdown_key(workspace_id: UUID, file_id: UUID, revision_id: UUID) -> str:
    """Build the private object key for extracted revision markdown."""
    key = f"workspaces/{workspace_id}/files/{file_id}/{revision_id}.extracted.md"
    make_storage_object_ref(StorageBucket.PRIVATE, key)
    return key


def file_prefix(workspace_id: UUID, file_id: UUID) -> str:
    """Build the object-key prefix for all blobs belonging to a file."""
    return validate_object_key(f"workspaces/{workspace_id}/files/{file_id}")


def require_file_write_access(membership: WorkspaceMembership) -> None:
    """Require workspace write access for file mutations."""
    if membership.role not in EDITOR_ROLES:
        raise AuthorizationError(
            "Requires workspace write access",
            details={
                "allowed_roles": sorted(EDITOR_ROLES),
                "membership_id": str(membership.id),
                "membership_role": membership.role,
                "workspace_id": str(membership.workspace_id),
                "user_id": str(membership.user_id),
            },
        )


def require_file_purge_access(membership: WorkspaceMembership) -> None:
    """Require manager access for irreversible file purges."""
    if membership.role not in MANAGER_ROLES:
        raise AuthorizationError(
            "Requires workspace manager access",
            details={
                "allowed_roles": sorted(MANAGER_ROLES),
                "membership_id": str(membership.id),
                "membership_role": membership.role,
                "workspace_id": str(membership.workspace_id),
                "user_id": str(membership.user_id),
            },
        )


async def get_file_for_workspace(
    db: AsyncSession,
    *,
    workspace: Workspace,
    file_id: UUID,
    include_deleted: bool = False,
    for_update: bool = False,
) -> File:
    """Fetch one workspace file, or raise NotFoundError."""
    stmt = select(File).where(File.id == file_id, File.workspace_id == workspace.id)
    if not include_deleted:
        stmt = stmt.where(File.deleted.is_(False))
    if for_update:
        stmt = stmt.with_for_update()
    file = await db.scalar(stmt)
    if file is None:
        raise NotFoundError("File not found", resource_type="file", resource_id=str(file_id))
    return file


async def get_folder_for_workspace(
    db: AsyncSession,
    *,
    workspace: Workspace,
    folder_id: UUID,
    include_deleted: bool = False,
    for_update: bool = False,
) -> FileFolder:
    """Fetch one workspace folder, or raise NotFoundError."""
    stmt = select(FileFolder).where(
        FileFolder.id == folder_id,
        FileFolder.workspace_id == workspace.id,
    )
    if not include_deleted:
        stmt = stmt.where(FileFolder.deleted.is_(False))
    if for_update:
        stmt = stmt.with_for_update()
    folder = await db.scalar(stmt)
    if folder is None:
        raise NotFoundError(
            "File folder not found",
            resource_type="file_folder",
            resource_id=str(folder_id),
        )
    return folder


def private_ref_from_key(object_key: str):
    """Return a private storage ref for a workspace file object key."""
    return make_storage_object_ref(StorageBucket.PRIVATE, object_key)


async def best_effort_delete_file_object(
    object_key: str | None,
    *,
    provider: StorageProvider | None = None,
    bucket: StorageBucket = StorageBucket.PRIVATE,
) -> None:
    """Delete a private file object without failing the surrounding operation."""
    if not object_key:
        return
    try:
        storage_provider = provider or get_storage_provider()
        await storage_provider.delete_object(make_storage_object_ref(bucket, object_key))
    except Exception:
        logger.warning(
            "Failed to delete private file object",
            extra={"bucket": bucket.value, "object_key": object_key},
            exc_info=True,
        )


def distinct_object_keys(revisions: list[FileRevision]) -> set[str]:
    """Return distinct original and markdown object keys for revisions."""
    keys: set[str] = set()
    for revision in revisions:
        keys.add(revision.object_key)
        if revision.markdown_object_key:
            keys.add(revision.markdown_object_key)
    return keys


async def set_processing_state_for_revision(
    db: AsyncSession,
    *,
    file: File,
    revision: FileRevision,
    initiated_by_user_id: UUID | None,
) -> None:
    """Set file processing state and enqueue extraction for ingestible revisions."""
    from services.files.contract import is_ingestible
    from services.jobs.enqueue_job import enqueue_job

    file.processing_error = None
    file.processing_attempts = 0
    if not is_ingestible(revision.content_type):
        file.processing_status = "ready"
        return

    file.processing_status = "pending"
    await enqueue_job(
        db,
        kind="files.extract_platform" if file.scope == ContentScope.PLATFORM else "files.extract",
        workspace_id=file.workspace_id,
        concurrency_user_id=initiated_by_user_id if file.scope == ContentScope.PLATFORM else None,
        subject_type="file_revision",
        subject_id=revision.id,
        payload={"file_id": str(file.id), "revision_id": str(revision.id)},
        content_hash=revision.content_hash,
        initiated_by_user_id=initiated_by_user_id,
    )


async def get_file_folder_name(
    db: AsyncSession,
    *,
    workspace: Workspace,
    file: File,
) -> str | None:
    """Resolve the current live folder name for a file response."""
    if file.folder_id is None:
        return None
    return (
        await get_folder_for_workspace(
            db,
            workspace=workspace,
            folder_id=file.folder_id,
        )
    ).name


def file_to_read(file: File, *, folder_name: str | None, actor: User | None = None) -> FileRead:
    """Serialize a file model for API responses."""
    if file.current_revision_id is None:
        raise RuntimeError("Workspace file has no current revision")
    return FileRead(
        id=file.id,
        scope=file.scope,
        is_published=file.is_published,
        published_revision_id=file.published_revision_id,
        can_manage_platform=can_manage_platform_content(
            scope=file.scope,
            deleted=file.deleted,
            actor=actor,
        ),
        workspace_id=file.workspace_id,
        name=file.name,
        description=file.description,
        folder_id=file.folder_id,
        folder_name=folder_name,
        category=file.category,
        content_type=file.content_type,
        extension=file.extension,
        size_bytes=file.size_bytes,
        content_hash=file.content_hash,
        current_revision_id=file.current_revision_id,
        revision_count=file.revision_count,
        processing_status=file.processing_status,
        processing_error=file.processing_error,
        created_at=file.created_at,
        updated_at=file.updated_at,
    )


def revision_to_read(revision: FileRevision) -> FileRevisionRead:
    """Serialize a file revision model for API responses."""
    return FileRevisionRead(
        id=revision.id,
        revision_number=revision.revision_number,
        revision_kind=revision.revision_kind,
        content_type=revision.content_type,
        size_bytes=revision.size_bytes,
        content_hash=revision.content_hash,
        created_by_user_id=revision.created_by_user_id,
        created_by_agent_id=revision.created_by_agent_id,
        created_by_system=revision.created_by_system,
        restored_from_revision_id=revision.restored_from_revision_id,
        created_at=revision.created_at,
    )


def file_storage_bucket(scope: ContentScope | str) -> StorageBucket:
    """Returns the explicit private storage class for a file owner."""
    return (
        StorageBucket.PLATFORM_PRIVATE
        if ContentScope(scope) == ContentScope.PLATFORM
        else StorageBucket.PRIVATE
    )


def file_storage_prefix(scope: ContentScope | str, workspace_id: UUID | None) -> str:
    """Validates ownership before constructing a private file namespace."""
    if ContentScope(scope) == ContentScope.PLATFORM and workspace_id is None:
        return "platform"
    if ContentScope(scope) == ContentScope.WORKSPACE and workspace_id is not None:
        return f"workspaces/{workspace_id}"
    raise AppValidationError("Invalid file storage owner")


async def get_file_for_upload(
    db: AsyncSession,
    *,
    scope: ContentScope,
    workspace_id: UUID | None,
    file_id: UUID,
) -> File:
    """Resolves an upload target within its authorised ownership boundary."""
    stmt = select(File).where(
        File.id == file_id,
        File.scope == scope,
        File.workspace_id == workspace_id,
        File.deleted.is_(False),
    )
    file = await db.scalar(stmt)
    if file is None:
        raise NotFoundError("File not found", resource_type="file", resource_id=str(file_id))
    return file


def require_declared_upload_size(actual_size: int, upload: FileUpload) -> None:
    """Rejects bytes that differ from the persisted upload declaration."""
    if actual_size != upload.declared_size_bytes:
        raise AppValidationError(
            "Uploaded file size does not match the declared size", field="size_bytes"
        )


def apply_file_metadata_update(
    file: File, *, name: str | None, description: str | None, fields_set: set[str]
) -> list[str]:
    """Updates metadata while preserving the file extension."""
    changed_fields: list[str] = []
    if "name" in fields_set and name is not None:
        filename = safe_filename(name)
        if PurePosixPath(filename).suffix.lower() != file.extension:
            raise AppValidationError("File rename must keep the existing extension", field="name")
        if filename != file.name:
            file.name = filename
            changed_fields.append("name")
    if "description" in fields_set and description != file.description:
        file.description = description
        changed_fields.append("description")
    return changed_fields


async def append_restore_revision(
    db: AsyncSession, *, file: File, source: FileRevision, actor: User
) -> FileRevision:
    """Appends an immutable restore revision after the caller locks and validates the parent."""
    revision = FileRevision(
        id=uuid4(),
        file_id=file.id,
        workspace_id=file.workspace_id,
        scope=file.scope,
        revision_number=file.revision_count + 1,
        revision_kind="restore",
        content_type=source.content_type,
        extension=source.extension,
        size_bytes=source.size_bytes,
        content_hash=source.content_hash,
        object_key=source.object_key,
        created_by_user_id=actor.id,
        restored_from_revision_id=source.id,
    )
    db.add(revision)
    await db.flush()
    file.current_revision_id = revision.id
    if file.scope == ContentScope.PLATFORM and not file.is_published:
        # A fresh draft can process after withdrawal cancelled the previous revision.
        file.published_revision_id = None
    file.revision_count = revision.revision_number
    file.content_type = revision.content_type
    file.extension = revision.extension
    file.size_bytes = revision.size_bytes
    file.content_hash = revision.content_hash
    await set_processing_state_for_revision(
        db, file=file, revision=revision, initiated_by_user_id=actor.id
    )
    await db.flush()
    return revision
