# apps/api/services/files/add_first_revision.py

"""Adds a new File row and its first revision row."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.files import File, FileRevision
from models.workspace import Workspace
from services.files.contract import FileContractEntry
from services.files.queue_video_probe import queue_video_probe
from services.files.revision_actor import FileRevisionActor


async def add_first_revision(
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
