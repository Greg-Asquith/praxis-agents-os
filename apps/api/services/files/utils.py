# apps/api/services/files/utils.py

"""Helpers specific to workspace file services."""

import hashlib
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.auth import AuthorizationError
from core.exceptions.general import NotFoundError
from models.files import File, FileRevision
from models.workspace import Workspace, WorkspaceMembership
from services.files.domain import FileRead, FileRevisionRead
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider
from services.storage.paths import validate_object_key
from services.storage.provider import StorageProvider
from services.workspaces.utils import EDITOR_ROLES, MANAGER_ROLES

logger = logging.getLogger(__name__)


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


def sha256_hex(data: bytes) -> str:
    """Return a lowercase sha256 hex digest for bytes."""
    return hashlib.sha256(data).hexdigest()


def private_ref_from_key(object_key: str):
    """Return a private storage ref for a workspace file object key."""
    return make_storage_object_ref(StorageBucket.PRIVATE, object_key)


async def best_effort_delete_file_object(
    object_key: str | None,
    *,
    provider: StorageProvider | None = None,
) -> None:
    """Delete a private file object without failing the surrounding operation."""
    if not object_key:
        return
    try:
        storage_provider = provider or get_storage_provider()
        await storage_provider.delete_object(private_ref_from_key(object_key))
    except Exception:
        logger.warning(
            "Failed to delete private workspace file object",
            extra={"object_key": object_key},
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
        kind="files.extract",
        workspace_id=file.workspace_id,
        subject_type="file_revision",
        subject_id=revision.id,
        payload={"file_id": str(file.id), "revision_id": str(revision.id)},
        content_hash=revision.content_hash,
        initiated_by_user_id=initiated_by_user_id,
    )


def file_to_read(file: File) -> FileRead:
    """Serialize a file model for API responses."""
    if file.current_revision_id is None:
        raise RuntimeError("Workspace file has no current revision")
    return FileRead(
        id=file.id,
        workspace_id=file.workspace_id,
        name=file.name,
        description=file.description,
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
