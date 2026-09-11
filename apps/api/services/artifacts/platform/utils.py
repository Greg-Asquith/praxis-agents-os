# apps/api/services/artifacts/platform/utils.py

"""Scoped authority, revision checks, and strict Artifact publication."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import maintenance_async_db_session
from core.dependencies import is_super_admin_email, require_super_admin_user
from core.exceptions.auth import AuthorizationError
from core.exceptions.general import AppValidationError, ConflictError, NotFoundError
from core.settings import settings
from models.artifacts import Artifact, ArtifactRevision
from models.jobs import Job
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.artifacts.domain import (
    ARTIFACT_EXTENSIONS,
    ARTIFACT_STORAGE_CONTENT_TYPES,
    CLEANUP_PLATFORM_ARTIFACT_OBJECT_KIND,
)
from services.artifacts.platform.content_validation.utils import validate_platform_content
from services.artifacts.platform.schemas import PlatformArtifactRead
from services.artifacts.utils import (
    artifact_content_hash,
    artifact_to_read,
    can_edit_artifact,
    validate_artifact_content,
)
from services.artifacts.visibility import visible_artifact_filter
from services.audit_events import AuditResourceType
from services.audit_events.platform_content_events import (
    PlatformContentAuditDetails,
    record_platform_content_audit_event,
)
from services.jobs.domain import JOB_STATUS_PENDING
from services.jobs.enqueue_job import enqueue_job
from services.storage.domain import StorageBucket, make_storage_object_ref
from services.storage.factory import get_storage_provider
from services.storage.utils import await_copy_mutation, read_copy_content
from services.workspaces.utils import EDITOR_ROLES


async def live_authority(
    db: AsyncSession, *, actor: User, workspace: Workspace, lock: bool
) -> tuple[User, WorkspaceMembership]:
    """Locks active authority through the mutation commit, including membership revocation."""
    statements = (
        select(User).where(User.id == actor.id, User.deleted.is_(False), User.is_active.is_(True)),
        select(Workspace).where(
            Workspace.id == workspace.id, Workspace.deleted.is_(False), Workspace.status == "active"
        ),
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.user_id == actor.id,
            WorkspaceMembership.deleted.is_(False),
        ),
    )
    rows = []
    for statement in statements:
        if lock:
            statement = statement.with_for_update(read=True)
        row = await db.scalar(statement.execution_options(populate_existing=True))
        if row is None:
            raise AuthorizationError("An active workspace membership is required")
        rows.append(row)
    return rows[0], rows[2]


@asynccontextmanager
async def platform_session(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    artifact_id: UUID | None = None,
    editing: bool = False,
) -> AsyncIterator[tuple[AsyncSession, User, WorkspaceMembership]]:
    live_actor, membership = await live_authority(db, actor=actor, workspace=workspace, lock=False)
    if not editing:
        require_super_admin_user(live_actor)
    elif not is_super_admin_email(live_actor.email):
        artifact = await db.scalar(
            select(Artifact).where(
                Artifact.id == artifact_id,
                Artifact.scope == "platform",
                visible_artifact_filter(workspace.id),
            )
        )
        require_editor(artifact, actor=live_actor, membership=membership)
    await db.commit()
    async with maintenance_async_db_session() as maintenance_db:
        live_actor, membership = await live_authority(
            maintenance_db, actor=actor, workspace=workspace, lock=True
        )
        if not editing:
            require_super_admin_user(live_actor)
        yield maintenance_db, live_actor, membership


async def platform_artifact(
    db: AsyncSession, artifact_id: UUID, *, lock: bool = False, published_only: bool = False
) -> Artifact:
    statement = select(Artifact).where(
        Artifact.id == artifact_id,
        Artifact.scope == "platform",
        Artifact.workspace_id.is_(None),
        Artifact.deleted.is_(False),
    )
    if published_only:
        statement = statement.where(Artifact.is_published.is_(True))
    if lock:
        statement = statement.with_for_update()
    artifact = await db.scalar(statement.execution_options(populate_existing=True))
    if artifact is None:
        raise NotFoundError("Artifact not found", resource_type="artifact")
    return artifact


def require_editor(
    artifact: Artifact | None,
    *,
    actor: User,
    membership: WorkspaceMembership,
    runtime: bool = False,
) -> None:
    if runtime and membership.role not in EDITOR_ROLES:
        raise AuthorizationError("A workspace editor must request this Artifact update")
    if artifact is None or not can_edit_artifact(artifact, actor=actor, membership=membership):
        raise AuthorizationError(
            "Make a workspace copy or ask a workspace editor to edit this Artifact"
        )


def require_expected(artifact: Artifact, expected: UUID) -> None:
    if artifact.current_version_id != expected:
        raise ConflictError(
            "Artifact has changed. Review its latest version before saving.",
            conflicting_resource="artifact",
        )


async def platform_revision(
    db: AsyncSession, artifact: Artifact, version_id: UUID | None
) -> ArtifactRevision:
    revision = await db.scalar(
        select(ArtifactRevision).where(
            ArtifactRevision.id == version_id,
            ArtifactRevision.artifact_id == artifact.id,
            ArtifactRevision.scope == "platform",
            ArtifactRevision.workspace_id.is_(None),
        )
    )
    if revision is None:
        raise NotFoundError("Artifact version not found", resource_type="artifact")
    return revision


async def read_content(artifact: Artifact, revision: ArtifactRevision) -> bytes:
    if not 0 <= revision.size_bytes <= settings.ARTIFACT_MAX_CONTENT_BYTES:
        raise AppValidationError("Artifact content is too large")
    bucket = (
        StorageBucket.PLATFORM_PRIVATE if artifact.scope == "platform" else StorageBucket.PRIVATE
    )
    content = await read_copy_content(
        get_storage_provider(),
        make_storage_object_ref(bucket, revision.object_key),
        revision.size_bytes,
        revision.content_hash,
    )
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AppValidationError("Artifact content must be UTF-8 text") from exc
    validate_artifact_content(
        artifact_type=artifact.artifact_type, title=artifact.title, content=text
    )
    validate_platform_content(artifact_type=artifact.artifact_type, content=text)
    return content


async def to_read(
    db: AsyncSession, artifact: Artifact, actor: User, membership: WorkspaceMembership
) -> PlatformArtifactRead:
    statement = select(ArtifactRevision).where(
        ArtifactRevision.artifact_id == artifact.id,
        ArtifactRevision.scope == "platform",
        ArtifactRevision.workspace_id.is_(None),
    )
    if not is_super_admin_email(actor.email):
        statement = statement.where(ArtifactRevision.is_published.is_(True))
    revisions = list(
        await db.scalars(statement.order_by(ArtifactRevision.revision_number.desc()).limit(100))
    )
    result = artifact_to_read(artifact, revisions, actor=actor, membership=membership)
    if not is_super_admin_email(actor.email):
        restored_ids = {
            revision.restored_from_revision_id
            for revision in revisions
            if revision.restored_from_revision_id
        }
        published_sources = (
            set(
                await db.scalars(
                    select(ArtifactRevision.id).where(
                        ArtifactRevision.id.in_(restored_ids),
                        ArtifactRevision.artifact_id == artifact.id,
                        ArtifactRevision.scope == "platform",
                        ArtifactRevision.workspace_id.is_(None),
                        ArtifactRevision.is_published.is_(True),
                    )
                )
            )
            if restored_ids
            else set()
        )
        for version in result.versions:
            if version.restored_from_revision_id not in published_sources:
                version.restored_from_revision_id = None
    return PlatformArtifactRead(
        **result.model_dump(), published_version_id=artifact.published_version_id
    )


async def record_change(
    db: AsyncSession,
    *,
    artifact: Artifact,
    actor: User,
    membership: WorkspaceMembership,
    request: Request | None,
    details: PlatformContentAuditDetails,
) -> None:
    await db.flush()
    await record_platform_content_audit_event(
        db,
        request=request,
        actor=actor,
        resource_type=AuditResourceType.ARTIFACT,
        resource_id=artifact.id,
        details=details,
        artifact=artifact,
        membership=membership,
    )
    await db.refresh(artifact)


async def publish_revision(
    db: AsyncSession, artifact: Artifact, revision: ArtifactRevision
) -> None:
    await read_content(artifact, revision)
    revision.is_published = True
    await db.flush()
    artifact.current_version_id = revision.id
    artifact.published_version_id = revision.id
    artifact.is_published = True


async def reserve_revision(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    artifact_id: UUID,
    expected_current_version_id: UUID,
    published_only: bool = False,
) -> Job:
    """Commits cleanup ownership before the save acquires its maintenance connection."""
    async with platform_session(
        db, actor=actor, workspace=workspace, artifact_id=artifact_id, editing=True
    ) as (maintenance_db, actor, membership):
        artifact = await platform_artifact(
            maintenance_db, artifact_id, published_only=published_only
        )
        require_editor(artifact, actor=actor, membership=membership, runtime=published_only)
        require_expected(artifact, expected_current_version_id)
        return await enqueue_job(
            maintenance_db,
            kind=CLEANUP_PLATFORM_ARTIFACT_OBJECT_KIND,
            subject_type="artifact",
            subject_id=artifact_id,
            payload={
                "revision_id": str(uuid4()),
                "extension": ARTIFACT_EXTENSIONS[artifact.artifact_type],
            },
            run_after=datetime.now(UTC) + timedelta(minutes=5),
        )


async def append_revision(
    db: AsyncSession,
    *,
    artifact: Artifact,
    actor: User,
    membership: WorkspaceMembership,
    request: Request | None,
    content: str,
    title: str,
    reservation: Job,
    restored_from: ArtifactRevision | None = None,
) -> PlatformArtifactRead:
    """Saves immutable bytes and publishes edits under the locked live authority."""
    data = validate_artifact_content(
        artifact_type=artifact.artifact_type, title=title, content=content
    )
    validate_platform_content(artifact_type=artifact.artifact_type, content=content)
    previous = await platform_revision(db, artifact, artifact.current_version_id)
    # Prevent claiming cleanup until the save commits or rolls back.
    cleanup_job = await db.scalar(
        select(Job)
        .where(
            Job.id == reservation.id,
            Job.status == JOB_STATUS_PENDING,
            Job.attempts == 0,
        )
        .with_for_update()
    )
    if cleanup_job is None:
        raise ConflictError("Artifact save expired. Try saving again.")
    revision_id = UUID(reservation.payload["revision_id"])
    extension = ARTIFACT_EXTENSIONS[artifact.artifact_type]
    revision = ArtifactRevision(
        id=revision_id,
        artifact_id=artifact.id,
        scope="platform",
        workspace_id=None,
        revision_number=previous.revision_number + 1,
        revision_kind="restore" if restored_from else "edit",
        content_type=ARTIFACT_STORAGE_CONTENT_TYPES[artifact.artifact_type],
        extension=extension,
        size_bytes=len(data),
        content_hash=artifact_content_hash(data),
        object_key=f"platform/artifacts/{artifact.id}/{revision_id}{extension}",
        created_by_user_id=actor.id,
        created_by_system=False,
        restored_from_revision_id=restored_from.id if restored_from else None,
    )
    db.add(revision)
    await db.flush()
    ref = make_storage_object_ref(StorageBucket.PLATFORM_PRIVATE, revision.object_key)
    provider = get_storage_provider()
    await await_copy_mutation(
        provider.put_object(
            ref,
            data,
            content_type=revision.content_type,
            cache_control="private, no-store",
            overwrite=False,
        )
    )
    artifact.current_version_id = revision.id
    artifact.title = title.strip()
    operation = "restore" if restored_from else "update"
    if artifact.is_published:
        await publish_revision(db, artifact, revision)
        operation = "publish_revision"
    await record_change(
        db,
        artifact=artifact,
        actor=actor,
        membership=membership,
        request=request,
        details=PlatformContentAuditDetails(
            operation=operation,
            revision_id=revision.id,
            previous_revision_id=previous.id,
            changed_fields=["content", "title"],
        ),
    )
    return await to_read(db, artifact, actor, membership)
