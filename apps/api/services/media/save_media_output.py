# apps/api/services/media/save_media_output.py

"""Saves a staged renderer output as a workspace File."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.workspace import Workspace
from services.files.contract import contract_for_content_type, stored_max_size_bytes
from services.files.create_file_from_stored_revision import create_file_from_stored_revision
from services.files.create_file_with_revision import FileRevisionWriteResult
from services.files.reserve_file_revision import reserve_file_revision
from services.files.revision_actor import FileRevisionActor
from services.files.utils import (
    best_effort_delete_file_object,
    private_ref_from_key,
    sha256_hex_stream,
)
from services.media.domain import MEDIA_STAGING_PREFIX, MediaRendererError, StagedMediaOutput
from services.storage.domain import StorageBucket
from services.storage.errors import StorageError
from services.storage.factory import get_storage_provider
from services.storage.utils import await_copy_mutation


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

    The storage provider copies the bytes, so an output can be as large as an
    uploaded video without passing through API memory. A committed reservation
    owns the copied object until the caller commits, so the upload sweeper
    removes it if the transaction never does. Staging is kept as the retry
    source; discard it after commit with ``discard_staged_outputs``, or leave it
    to the one-day lifecycle rule.
    """
    if output.ref.bucket != StorageBucket.PLATFORM_PRIVATE or not output.ref.key.startswith(
        f"{MEDIA_STAGING_PREFIX}/{workspace.id}/"
    ):
        raise MediaRendererError("forbidden", "The output isn't from this workspace.")
    limit = stored_max_size_bytes(contract_for_content_type(output.content_type))
    if output.size_bytes > limit:
        raise AppValidationError(
            "File content is too large",
            field="content",
            details={"content_bytes": output.size_bytes, "max_bytes": limit},
        )
    reservation = await reserve_file_revision(
        db,
        workspace_id=workspace.id,
        user_id=user_id,
        name=name,
        size_bytes=output.size_bytes,
        content_hash=output.sha256,
        content_type=output.content_type,
        extension=output.extension,
    )
    provider = get_storage_provider()
    destination = private_ref_from_key(reservation.object_key)
    try:
        stored = await await_copy_mutation(
            provider.import_staged_object(output.ref, destination, expected_source_etag=output.etag)
        )
        content_hash = await sha256_hex_stream(provider.stream_object(destination))
    except StorageError as exc:
        raise MediaRendererError("invalid_response", "The media renderer output changed.") from exc
    if stored.size_bytes != output.size_bytes or content_hash != output.sha256:
        await best_effort_delete_file_object(reservation.object_key, provider=provider)
        raise MediaRendererError("invalid_response", "The media renderer output changed.")
    return await create_file_from_stored_revision(
        db,
        workspace=workspace,
        name=name,
        reservation=reservation,
        stored=stored,
        content_hash=content_hash,
        actor=actor,
        folder_id=folder_id,
    )
