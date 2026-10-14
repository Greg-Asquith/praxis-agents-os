# apps/api/services/files/create_file_with_revision.py

"""Create a logical file and its first immutable revision."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from models.files import File, FileFolder, FileRevision, FileUpload
from models.workspace import Workspace
from services.files.add_first_revision import add_first_revision
from services.files.contract import require_matching_pair, require_written_size
from services.files.revision_actor import FileRevisionActor
from services.files.utils import (
    private_ref_from_key,
    require_reservation_match,
    revision_object_key,
    sha256_hex,
    target_folder_id,
)
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
    folder_id = await target_folder_id(
        db, workspace=workspace, folder_id=folder_id, resolved_folder=resolved_folder
    )
    file_id = reservation.file_id if reservation is not None else uuid4()
    revision_id = reservation.revision_id if reservation is not None else uuid4()
    object_key = revision_object_key(workspace.id, file_id, revision_id, extension)
    content_hash = sha256_hex(content)
    if reservation is not None:
        require_reservation_match(
            reservation,
            workspace=workspace,
            object_key=object_key,
            content_type=contract.content_type,
            size_bytes=len(content),
            content_hash=content_hash,
        )
    file, revision = await add_first_revision(
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
