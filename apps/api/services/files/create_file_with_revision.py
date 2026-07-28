# apps/api/services/files/create_file_with_revision.py

"""Create a logical file and its first immutable revision."""

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from models.files import File, FileRevision
from models.workspace import Workspace
from services.files.contract import require_matching_pair
from services.files.revision_actor import FileRevisionActor
from services.files.utils import private_ref_from_key, revision_object_key, sha256_hex
from services.storage.factory import get_storage_provider
from services.storage.utils import put_new_object_with_cleanup


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
) -> FileRevisionWriteResult:
    """Create a file through the shared immutable-revision seam."""
    actor.validate()
    contract = require_matching_pair(content_type, extension)
    file_id = uuid4()
    revision_id = uuid4()
    object_key = revision_object_key(workspace.id, file_id, revision_id, extension)
    content_hash = sha256_hex(content)
    file = File(
        id=file_id,
        workspace_id=workspace.id,
        name=name,
        category=contract.category.value,
        content_type=contract.content_type,
        extension=extension,
        size_bytes=len(content),
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
        size_bytes=len(content),
        content_hash=content_hash,
        object_key=object_key,
        **actor.columns(),
    )
    db.add(revision)
    await db.flush()
    file.current_revision_id = revision.id
    file.revision_count = 1
    await db.flush()
    await db.refresh(file)
    await put_new_object_with_cleanup(
        get_storage_provider(),
        private_ref_from_key(object_key),
        content,
        content_type=contract.content_type,
    )
    return FileRevisionWriteResult(file=file, revision=revision, bytes_written=len(content))
