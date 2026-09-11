# apps/api/services/artifacts/platform/create_artifact.py

"""Publishes one reviewed workspace version into independent platform ownership."""

from uuid import UUID, uuid5

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.dependencies import require_super_admin_user
from core.exceptions.general import ConflictError
from models.artifacts import Artifact, ArtifactRevision
from models.user import User
from models.workspace import Workspace
from services.artifacts.platform.schemas import PlatformArtifactCreateRequest, PlatformArtifactRead
from services.artifacts.platform.utils import (
    platform_revision,
    platform_session,
    publish_revision,
    read_content,
    record_change,
    require_expected,
    to_read,
)
from services.artifacts.utils import get_artifact_revision, get_artifact_row
from services.audit_events.platform_content_events import (
    PlatformContentAuditDetails,
    PlatformContentSource,
)
from services.storage.copy_object import copy_object
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider


async def create_artifact(
    db: AsyncSession,
    *,
    request: Request,
    actor: User,
    workspace: Workspace,
    artifact_id: UUID,
    payload: PlatformArtifactCreateRequest,
) -> PlatformArtifactRead:
    destination_id = uuid5(
        artifact_id,
        f"platform:{workspace.id}:{actor.id}:{payload.version_id}:{payload.expected_current_version_id}:{payload.request_id}",
    )
    revision_id = uuid5(destination_id, "revision")
    # The unpublished revision owns the deterministic object even after process interruption.
    async with platform_session(db, actor=actor, workspace=workspace) as (
        maintenance_db,
        actor,
        membership,
    ):
        source = await get_artifact_row(
            maintenance_db,
            workspace_id=workspace.id,
            artifact_id=artifact_id,
            for_update=True,
            workspace_only=True,
        )
        require_expected(source, payload.expected_current_version_id)
        source_revision = await get_artifact_revision(
            maintenance_db, artifact=source, version_id=payload.version_id
        )
        await read_content(source, source_revision)
        artifact = await maintenance_db.get(Artifact, destination_id)
        if artifact is None:
            artifact = Artifact(
                id=destination_id,
                scope="platform",
                workspace_id=None,
                title=source.title,
                artifact_type=source.artifact_type,
            )
            maintenance_db.add(artifact)
            await maintenance_db.flush()
            revision = ArtifactRevision(
                id=revision_id,
                artifact_id=artifact.id,
                scope="platform",
                workspace_id=None,
                revision_number=1,
                revision_kind="create",
                content_type=source_revision.content_type,
                extension=source_revision.extension,
                size_bytes=source_revision.size_bytes,
                content_hash=source_revision.content_hash,
                object_key=f"platform/artifacts/{artifact.id}/{revision_id}{source_revision.extension}",
                created_by_user_id=actor.id,
                created_by_system=False,
            )
            maintenance_db.add(revision)
            await maintenance_db.flush()
            artifact.current_version_id = revision.id
            await record_change(
                maintenance_db,
                artifact=artifact,
                actor=actor,
                membership=membership,
                request=request,
                details=PlatformContentAuditDetails(
                    operation="create",
                    revision_id=revision.id,
                    source=PlatformContentSource(
                        workspace_id=workspace.id,
                        resource_id=source.id,
                        revision_id=source_revision.id,
                    ),
                ),
            )

    async with platform_session(db, actor=actor, workspace=workspace) as (
        maintenance_db,
        actor,
        membership,
    ):
        source = await get_artifact_row(
            maintenance_db,
            workspace_id=workspace.id,
            artifact_id=artifact_id,
            for_update=True,
            workspace_only=True,
        )
        require_expected(source, payload.expected_current_version_id)
        source_revision = await get_artifact_revision(
            maintenance_db, artifact=source, version_id=payload.version_id
        )
        artifact = await maintenance_db.scalar(
            select(Artifact)
            .where(
                Artifact.id == destination_id,
                Artifact.scope == "platform",
                Artifact.workspace_id.is_(None),
            )
            .with_for_update()
        )
        if artifact is None or artifact.deleted:
            raise ConflictError("The platform publication was deleted. Start a new publication.")
        revision = await platform_revision(maintenance_db, artifact, revision_id)
        if revision.is_published:
            if not artifact.is_published:
                raise ConflictError(
                    "The platform publication was withdrawn. Review it before publishing again."
                )
            return await to_read(maintenance_db, artifact, actor, membership)
        require_expected(artifact, revision_id)

        async def authorise(_source, _destination) -> None:
            # Source and authority rows remain locked until publication commits.
            require_super_admin_user(actor)
            require_expected(source, payload.expected_current_version_id)
            require_expected(artifact, revision_id)

        await copy_object(
            get_storage_provider(),
            make_storage_object_ref(StorageBucket.PRIVATE, source_revision.object_key),
            make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, revision.object_key),
            authorise=authorise,
            expected_size_bytes=revision.size_bytes,
            expected_sha256=revision.content_hash,
            content_type=revision.content_type,
        )
        await publish_revision(maintenance_db, artifact, revision)
        await record_change(
            maintenance_db,
            artifact=artifact,
            actor=actor,
            membership=membership,
            request=request,
            details=PlatformContentAuditDetails(
                operation="publish",
                revision_id=revision.id,
                source=PlatformContentSource(
                    workspace_id=workspace.id, resource_id=source.id, revision_id=source_revision.id
                ),
            ),
        )
        return await to_read(maintenance_db, artifact, actor, membership)
