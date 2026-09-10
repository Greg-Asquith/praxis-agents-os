# apps/api/services/files/copy_file.py

"""Copy one published platform revision into independent workspace ownership."""

from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from uuid import UUID, uuid5

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import maintenance_async_db_session
from core.exceptions.general import NotFoundError
from core.settings import settings
from models.files import File, FileRevision, FileUpload
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.audit_events import AuditAction, AuditActorType, AuditResourceType
from services.audit_events.operations import record_operation_audit_event
from services.files.domain import FileCopyRequest, FileRead
from services.files.utils import (
    file_to_read,
    get_file_copy_source,
    get_file_folder_name,
    require_file_copy_editor,
    require_file_write_access,
    revision_object_key,
    set_processing_state_for_revision,
)
from services.storage.copy_object import copy_object
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider


async def copy_file(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    membership: WorkspaceMembership,
    file_id: UUID,
    payload: FileCopyRequest,
) -> FileRead:
    """Retains a copy reservation so retries and expiry cleanup own every object."""
    require_file_write_access(membership)
    await require_file_copy_editor(db, actor=actor, workspace=workspace)
    source, revision = await get_file_copy_source(
        db, workspace=workspace, file_id=file_id, revision_id=payload.revision_id
    )
    destination_id = uuid5(
        workspace.id, f"file-copy:{actor.id}:{file_id}:{revision.id}:{payload.request_id}"
    )
    revision_id = uuid5(destination_id, "revision")
    destination = make_storage_object_ref(
        StorageBucket.PRIVATE,
        revision_object_key(workspace.id, destination_id, revision_id, revision.extension),
    )
    reservation = await db.scalar(
        select(FileUpload)
        .where(FileUpload.id == destination_id, FileUpload.workspace_id == workspace.id)
        .with_for_update()
    )
    if reservation is None:
        reservation = FileUpload(
            id=destination_id,
            workspace_id=workspace.id,
            scope="workspace",
            file_id=destination_id,
            revision_id=revision_id,
            object_key=destination.key,
            filename=str(PurePosixPath(source.name).with_suffix(revision.extension)),
            content_type=revision.content_type,
            declared_size_bytes=revision.size_bytes,
            declared_content_hash=revision.content_hash,
            created_by_user_id=actor.id,
            expires_at=datetime.now(UTC) + timedelta(hours=settings.FILES_UPLOAD_EXPIRY_HOURS),
        )
        db.add(reservation)
    await db.commit()

    # Only the already authorised platform parent is locked with maintenance access.
    # Tenant RLS deliberately denies row locks that imply platform write authority.
    async with maintenance_async_db_session() as source_db:
        try:
            source, revision = await get_file_copy_source(
                source_db,
                workspace=workspace,
                file_id=file_id,
                revision_id=payload.revision_id,
                lock=True,
            )
            await require_file_copy_editor(db, actor=actor, workspace=workspace)
            reservation = await db.scalar(
                select(FileUpload)
                .where(FileUpload.id == destination_id, FileUpload.workspace_id == workspace.id)
                .with_for_update()
            )
            if reservation is None:
                raise NotFoundError("Copy request expired. Start a new workspace copy.")
            existing = await db.scalar(
                select(File).where(
                    File.id == destination_id,
                    File.workspace_id == workspace.id,
                    File.deleted.is_(False),
                )
            )
            if existing is not None:
                result = file_to_read(
                    existing,
                    folder_name=await get_file_folder_name(db, workspace=workspace, file=existing),
                )
                await db.commit()
                return result

            if reservation.consumed_at is not None:
                raise NotFoundError("Workspace copy no longer exists. Start a new copy.")

            async def authorise(_source, _destination) -> None:
                await require_file_copy_editor(db, actor=actor, workspace=workspace)
                await get_file_copy_source(
                    source_db, workspace=workspace, file_id=file_id, revision_id=payload.revision_id
                )

            await copy_object(
                get_storage_provider(),
                make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, revision.object_key),
                destination,
                authorise=authorise,
                expected_size_bytes=revision.size_bytes,
                expected_sha256=revision.content_hash,
                content_type=revision.content_type,
            )
            file = File(
                id=destination_id,
                workspace_id=workspace.id,
                scope="workspace",
                name=str(PurePosixPath(source.name).with_suffix(revision.extension)),
                description=source.description,
                category=source.category,
                content_type=revision.content_type,
                extension=revision.extension,
                size_bytes=revision.size_bytes,
                content_hash=revision.content_hash,
                revision_count=0,
                processing_status="ready",
                processing_attempts=0,
            )
            db.add(file)
            await db.flush()
            local_revision = FileRevision(
                id=revision_id,
                file_id=file.id,
                workspace_id=workspace.id,
                scope="workspace",
                revision_number=1,
                revision_kind="create",
                content_type=revision.content_type,
                extension=revision.extension,
                size_bytes=revision.size_bytes,
                content_hash=revision.content_hash,
                object_key=destination.key,
                created_by_user_id=actor.id,
            )
            db.add(local_revision)
            await db.flush()
            file.current_revision_id = local_revision.id
            file.revision_count = 1
            await set_processing_state_for_revision(
                db, file=file, revision=local_revision, initiated_by_user_id=actor.id
            )
            reservation.consumed_at = datetime.now(UTC)
            await record_operation_audit_event(
                db,
                request=request,
                workspace_id=workspace.id,
                action=AuditAction.CREATE,
                resource_type=AuditResourceType.FILE,
                resource_id=file.id,
                actor_type=AuditActorType.USER,
                actor_id=actor.id,
                actor_display=actor.email,
                requested_by_user_id=actor.id,
                details={
                    "operation": "copy",
                    "source_platform_file_id": str(source.id),
                    "source_revision_id": str(revision.id),
                },
            )
            await db.refresh(file)
            result = file_to_read(file, folder_name=None)
            await db.commit()
            return result
        except BaseException:
            await db.rollback()
            raise
