# apps/api/services/files/create_file_with_revision.py

"""Create a logical file and its first immutable revision."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from models.files import File, FileFolder, FileRevision, FileUpload
from models.workspace import Workspace
from services.files.contract import (
    FileContractEntry,
    require_matching_pair,
    require_written_size,
)
from services.files.queue_video_probe import queue_video_probe
from services.files.revision_actor import FileRevisionActor
from services.files.utils import (
    get_folder_for_workspace,
    private_ref_from_key,
    revision_object_key,
    sha256_hex,
)
from services.storage.domain import StoredObject
from services.storage.factory import get_storage_provider
from services.storage.utils import await_copy_mutation, put_new_object_with_cleanup


@dataclass(frozen=True)
class FileRevisionWriteResult:
    file: File
    revision: FileRevision
    bytes_written: int


async def create_file_with_revision(
    db: AsyncSession,
    *,
    workspace: Workspace,
    name: str,
    content: bytes,
    content_type: str,
    extension: str,
    actor: FileRevisionActor,
    folder_id: UUID | None = None,
    resolved_folder: FileFolder | None = None,
    reservation: FileUpload | None = None,
) -> FileRevisionWriteResult:
    """Creates a File and writes its first immutable revision.

    A reservation must be committed and locked by the caller until final commit
    or rollback. Its consumption commits atomically with the File.
    """
    actor.validate()
    contract = require_matching_pair(content_type, extension)
    require_written_size(contract, len(content))
    folder_id = await _target_folder_id(db, workspace, folder_id, resolved_folder)
    file_id = reservation.file_id if reservation is not None else uuid4()
    revision_id = reservation.revision_id if reservation is not None else uuid4()
    object_key = revision_object_key(workspace.id, file_id, revision_id, extension)
    content_hash = sha256_hex(content)
    if reservation is not None:
        _require_reservation_match(
            reservation,
            workspace=workspace,
            object_key=object_key,
            content_type=contract.content_type,
            size_bytes=len(content),
            content_hash=content_hash,
        )
    file, revision = await _add_file_rows(
        db,
        workspace=workspace,
        name=name,
        contract=contract,
        extension=extension,
        size_bytes=len(content),
        content_hash=content_hash,
        object_key=object_key,
        file_id=file_id,
        revision_id=revision_id,
        folder_id=folder_id,
        actor=actor,
    )
    provider = get_storage_provider()
    ref = private_ref_from_key(object_key)
    if reservation is None:
        await put_new_object_with_cleanup(
            provider, ref, content, content_type=contract.content_type
        )
    else:
        # Keep the reservation locked until any in-flight provider write has settled.
        await await_copy_mutation(
            provider.put_object(
                ref,
                content,
                content_type=contract.content_type,
                cache_control="private, no-store",
                overwrite=False,
            )
        )
        reservation.consumed_at = datetime.now(UTC)
        await db.flush()
    return FileRevisionWriteResult(file=file, revision=revision, bytes_written=len(content))


async def create_file_from_stored_revision(
    db: AsyncSession,
    *,
    workspace: Workspace,
    name: str,
    reservation: FileUpload,
    stored: StoredObject,
    content_hash: str,
    actor: FileRevisionActor,
    folder_id: UUID | None = None,
) -> FileRevisionWriteResult:
    """Creates a File whose first revision is already stored at the reservation's key.

    For content written by the storage provider, such as a copy that never passed
    through API memory. The caller has checked the object's size and hash; they
    must match the reservation, which is consumed atomically with the File.
    """
    actor.validate()
    extension = PurePosixPath(reservation.object_key).suffix
    contract = require_matching_pair(reservation.content_type, extension)
    if stored.ref != private_ref_from_key(reservation.object_key):
        raise ValueError("The stored object must be the reservation's object")
    _require_reservation_match(
        reservation,
        workspace=workspace,
        object_key=reservation.object_key,
        content_type=contract.content_type,
        size_bytes=stored.size_bytes,
        content_hash=content_hash,
    )
    file, revision = await _add_file_rows(
        db,
        workspace=workspace,
        name=name,
        contract=contract,
        extension=extension,
        size_bytes=stored.size_bytes,
        content_hash=content_hash,
        object_key=reservation.object_key,
        file_id=reservation.file_id,
        revision_id=reservation.revision_id,
        folder_id=await _target_folder_id(db, workspace, folder_id, None),
        actor=actor,
    )
    reservation.consumed_at = datetime.now(UTC)
    await db.flush()
    return FileRevisionWriteResult(file=file, revision=revision, bytes_written=stored.size_bytes)


async def _target_folder_id(
    db: AsyncSession,
    workspace: Workspace,
    folder_id: UUID | None,
    resolved_folder: FileFolder | None,
) -> UUID | None:
    if folder_id is not None and resolved_folder is not None:
        raise ValueError("Provide folder_id or resolved_folder, not both")
    if resolved_folder is not None:
        if resolved_folder.workspace_id != workspace.id or resolved_folder.deleted:
            raise ValueError("Resolved folder must be a live folder in the target workspace")
        return resolved_folder.id
    if folder_id is not None:
        await get_folder_for_workspace(
            db, workspace=workspace, folder_id=folder_id, for_update=True
        )
    return folder_id


def _require_reservation_match(
    reservation: FileUpload,
    *,
    workspace: Workspace,
    object_key: str,
    content_type: str,
    size_bytes: int,
    content_hash: str,
) -> None:
    if (
        reservation.workspace_id != workspace.id
        or reservation.scope != "workspace"
        or reservation.consumed_at is not None
        or reservation.object_key != object_key
        or reservation.content_type != content_type
        or reservation.declared_size_bytes != size_bytes
        or reservation.declared_content_hash != content_hash
    ):
        raise ValueError("File content must match its workspace reservation")


async def _add_file_rows(
    db: AsyncSession,
    *,
    workspace: Workspace,
    name: str,
    contract: FileContractEntry,
    extension: str,
    size_bytes: int,
    content_hash: str,
    object_key: str,
    file_id: UUID,
    revision_id: UUID,
    folder_id: UUID | None,
    actor: FileRevisionActor,
) -> tuple[File, FileRevision]:
    """Adds the File and its first revision, and queues a probe for video."""
    file = File(
        id=file_id,
        workspace_id=workspace.id,
        name=name,
        folder_id=folder_id,
        category=contract.category.value,
        content_type=contract.content_type,
        extension=extension,
        size_bytes=size_bytes,
        content_hash=content_hash,
        revision_count=0,
        processing_status="ready",
        processing_attempts=0,
    )
    db.add(file)
    await db.flush()
    revision = FileRevision(
        id=revision_id,
        file_id=file.id,
        workspace_id=workspace.id,
        revision_number=1,
        revision_kind="create",
        content_type=contract.content_type,
        extension=extension,
        size_bytes=size_bytes,
        content_hash=content_hash,
        object_key=object_key,
        **actor.columns(),
    )
    db.add(revision)
    await db.flush()
    file.current_revision_id = revision.id
    file.revision_count = 1
    await queue_video_probe(db, file=file, revision=revision, initiated_by_user_id=actor.user_id)
    await db.flush()
    await db.refresh(file)
    return file, revision
