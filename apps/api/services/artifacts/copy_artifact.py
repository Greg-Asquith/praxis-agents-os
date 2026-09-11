# apps/api/services/artifacts/copy_artifact.py

"""Copies a published platform version into independent workspace ownership."""

from uuid import UUID, uuid5

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import maintenance_async_db_session
from core.exceptions.general import ConflictError
from models.artifacts import Artifact, ArtifactRevision
from models.jobs import Job
from models.user import User
from models.workspace import Workspace
from services.artifacts.copies.utils import copy_source, require_copy_editor, reserve_copy
from services.artifacts.get_artifact import get_artifact
from services.artifacts.schemas import ArtifactCopyRequest, ArtifactRead
from services.artifacts.utils import artifact_revision_object_key, artifact_to_read
from services.audit_events import AuditAction, AuditActorType, AuditResourceType
from services.audit_events.operations import record_operation_audit_event
from services.jobs.domain import JOB_STATUS_PENDING
from services.storage.copy_object import copy_object
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider


async def copy_artifact(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    artifact_id: UUID,
    payload: ArtifactCopyRequest,
) -> ArtifactRead:
    await require_copy_editor(db, actor=actor, workspace=workspace)
    source, revision = await copy_source(
        db, workspace_id=workspace.id, artifact_id=artifact_id, version_id=payload.version_id
    )
    destination_id = uuid5(
        workspace.id,
        f"artifact-copy:{actor.id}:{artifact_id}:{revision.id}:{payload.request_id}",
    )
    revision_id = uuid5(destination_id, "revision")
    destination = make_storage_object_ref(
        StorageBucket.PRIVATE,
        artifact_revision_object_key(workspace.id, destination_id, revision_id, revision.extension),
    )
    reservation = await reserve_copy(
        db,
        actor=actor,
        workspace=workspace,
        artifact_id=destination_id,
        revision_id=revision_id,
        extension=revision.extension,
    )
    try:
        actor, membership = await require_copy_editor(
            db, actor=actor, workspace=workspace, lock=True
        )
        # Tenant RLS denies platform locks. Lock only the already authorised source.
        async with maintenance_async_db_session() as source_db:
            source, revision = await copy_source(
                source_db,
                workspace_id=workspace.id,
                artifact_id=artifact_id,
                version_id=payload.version_id,
                lock=True,
            )
            cleanup = await db.scalar(
                select(Job)
                .where(Job.id == reservation.id, Job.workspace_id == workspace.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            existing = await db.scalar(
                select(Artifact).where(
                    Artifact.id == destination_id,
                    Artifact.scope == "workspace",
                    Artifact.workspace_id == workspace.id,
                )
            )
            if existing is not None:
                result = await get_artifact(
                    db,
                    workspace_id=workspace.id,
                    artifact_id=existing.id,
                    actor=actor,
                    membership=membership,
                )
                await db.commit()
                return result
            if cleanup is None or cleanup.status != JOB_STATUS_PENDING or cleanup.attempts != 0:
                raise ConflictError("Copy request expired. Start a new workspace copy.")

            async def authorise(_source, _destination) -> None:
                await require_copy_editor(db, actor=actor, workspace=workspace, lock=True)
                await copy_source(
                    source_db,
                    workspace_id=workspace.id,
                    artifact_id=artifact_id,
                    version_id=payload.version_id,
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
            artifact = Artifact(
                id=destination_id,
                scope="workspace",
                workspace_id=workspace.id,
                title=source.title,
                artifact_type=source.artifact_type,
            )
            db.add(artifact)
            await db.flush()
            local_revision = ArtifactRevision(
                id=revision_id,
                artifact_id=artifact.id,
                scope="workspace",
                workspace_id=workspace.id,
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
            artifact.current_version_id = local_revision.id
            await record_operation_audit_event(
                db,
                request=request,
                workspace_id=workspace.id,
                action=AuditAction.CREATE,
                resource_type=AuditResourceType.ARTIFACT,
                resource_id=artifact.id,
                actor_type=AuditActorType.USER,
                actor_id=actor.id,
                actor_display=actor.email,
                requested_by_user_id=actor.id,
                details={
                    "operation": "copy",
                    "source_platform_artifact_id": str(source.id),
                    "source_version_id": str(revision.id),
                },
            )
            await db.refresh(artifact)
            result = artifact_to_read(
                artifact, [local_revision], actor=actor, membership=membership
            )
            await db.commit()
            return result
    except BaseException:
        await db.rollback()
        raise
