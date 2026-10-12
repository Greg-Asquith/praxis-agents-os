# apps/api/services/media/save_media_output.py

"""Saves a staged renderer output as a workspace File."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.workspace import Workspace
from services.files.contract import contract_for_content_type, require_written_size
from services.files.create_file_with_revision import (
    FileRevisionWriteResult,
    create_file_with_revision,
)
from services.files.reserve_file_revision import reserve_file_revision
from services.files.revision_actor import FileRevisionActor
from services.media.domain import MEDIA_STAGING_PREFIX, MediaRendererError, StagedMediaOutput
from services.storage.domain import StorageBucket
from services.storage.errors import StorageError
from services.storage.factory import get_storage_provider
from services.storage.utils import read_copy_content


async def save_media_output(
    db: AsyncSession,
    *,
    workspace: Workspace,
    user_id: UUID,
    output: StagedMediaOutput,
    name: str,
    actor: FileRevisionActor,
    folder_id: UUID | None = None,
) -> FileRevisionWriteResult:
    """Copies one staged output into a new File inside the caller's transaction.

    A committed reservation owns the File's bytes until the caller commits, so
    the upload sweeper removes them if the transaction never does. Staging is
    kept as the retry source; discard it after commit with
    ``discard_staged_outputs``, or leave it to the one-day lifecycle rule.
    Tool-written files keep the written-size limit, so a cut over
    ``MAX_FILE_SIZE_VIDEO`` is refused here even though the renderer produced it.
    """
    if output.ref.bucket != StorageBucket.PLATFORM_PRIVATE or not output.ref.key.startswith(
        f"{MEDIA_STAGING_PREFIX}/{workspace.id}/"
    ):
        raise MediaRendererError("forbidden", "The output isn't from this workspace.")
    require_written_size(contract_for_content_type(output.content_type), output.size_bytes)
    try:
        content = await read_copy_content(
            get_storage_provider(), output.ref, output.size_bytes, output.sha256
        )
    except StorageError as exc:
        raise MediaRendererError("invalid_response", "The media renderer output changed.") from exc
    reservation = await reserve_file_revision(
        db,
        workspace_id=workspace.id,
        user_id=user_id,
        name=name,
        content=content,
        content_type=output.content_type,
        extension=output.extension,
    )
    return await create_file_with_revision(
        db,
        workspace=workspace,
        name=name,
        content=content,
        content_type=output.content_type,
        extension=output.extension,
        actor=actor,
        folder_id=folder_id,
        reservation=reservation,
    )
