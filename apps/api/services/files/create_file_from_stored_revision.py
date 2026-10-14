# apps/api/services/files/create_file_from_stored_revision.py

"""Create a File whose first revision the storage provider already wrote."""

from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.files import FileUpload
from models.workspace import Workspace
from services.files.add_first_revision import add_first_revision
from services.files.contract import require_matching_pair
from services.files.create_file_with_revision import FileRevisionWriteResult
from services.files.revision_actor import FileRevisionActor
from services.files.utils import private_ref_from_key, require_reservation_match, target_folder_id
from services.storage.domain import StoredObject


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
    """Creates a File from the reservation's stored object; the caller checks its size and hash."""
    actor.validate()
    extension = PurePosixPath(reservation.object_key).suffix
    contract = require_matching_pair(reservation.content_type, extension)
    if stored.ref != private_ref_from_key(reservation.object_key):
        raise ValueError("The stored object must be the reservation's object")
    require_reservation_match(
        reservation,
        workspace=workspace,
        object_key=reservation.object_key,
        content_type=contract.content_type,
        size_bytes=stored.size_bytes,
        content_hash=content_hash,
    )
    file, revision = await add_first_revision(
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
        folder_id=await target_folder_id(db, workspace=workspace, folder_id=folder_id),
        actor=actor,
    )
    reservation.consumed_at = datetime.now(UTC)
    await db.flush()
    return FileRevisionWriteResult(file=file, revision=revision, bytes_written=stored.size_bytes)
