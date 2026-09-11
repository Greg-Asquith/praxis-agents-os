# apps/api/services/artifacts/copies/utils.py

"""Authority, pinned source validation, and durable copy reservations."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.auth import AuthorizationError
from core.exceptions.general import AppValidationError, NotFoundError
from core.settings import settings
from models.artifacts import Artifact, ArtifactRevision
from models.jobs import Job
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.artifacts.domain import (
    ARTIFACT_EXTENSIONS,
    ARTIFACT_STORAGE_CONTENT_TYPES,
    CLEANUP_ARTIFACT_COPY_KIND,
)
from services.artifacts.platform.utils import live_authority
from services.artifacts.utils import get_artifact_revision, get_artifact_row
from services.jobs.enqueue_job import enqueue_job
from services.workspaces.utils import EDITOR_ROLES


async def require_copy_editor(
    db: AsyncSession, *, actor: User, workspace: Workspace, lock: bool = False
) -> tuple[User, WorkspaceMembership]:
    actor, membership = await live_authority(db, actor=actor, workspace=workspace, lock=lock)
    if membership.role not in EDITOR_ROLES:
        raise AuthorizationError("Requires workspace write access")
    return actor, membership


async def copy_source(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    artifact_id: UUID,
    version_id: UUID,
    lock: bool = False,
) -> tuple[Artifact, ArtifactRevision]:
    artifact = await get_artifact_row(
        db,
        workspace_id=workspace_id,
        artifact_id=artifact_id,
        for_update=lock,
    )
    if artifact.scope != "platform":
        raise NotFoundError("Published platform Artifact not found", resource_type="artifact")
    revision = await get_artifact_revision(db, artifact=artifact, version_id=version_id)
    if (
        artifact.artifact_type not in ARTIFACT_EXTENSIONS
        or revision.extension != ARTIFACT_EXTENSIONS[artifact.artifact_type]
        or revision.content_type != ARTIFACT_STORAGE_CONTENT_TYPES[artifact.artifact_type]
    ):
        raise AppValidationError("Unsupported Artifact content")
    if not 0 <= revision.size_bytes <= settings.ARTIFACT_MAX_CONTENT_BYTES:
        raise AppValidationError("Artifact content is too large")
    return artifact, revision


async def reserve_copy(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    artifact_id: UUID,
    revision_id: UUID,
    extension: str,
) -> Job:
    """Commits the object owner before copying or acquiring the source lock."""
    reservation = await db.scalar(
        select(Job)
        .where(
            Job.workspace_id == workspace.id,
            Job.kind == CLEANUP_ARTIFACT_COPY_KIND,
            Job.subject_type == "artifact",
            Job.subject_id == artifact_id,
        )
        .order_by(Job.created_at.desc())
        .limit(1)
    )
    if reservation is None:
        reservation = await enqueue_job(
            db,
            kind=CLEANUP_ARTIFACT_COPY_KIND,
            workspace_id=workspace.id,
            subject_type="artifact",
            subject_id=artifact_id,
            payload={"revision_id": str(revision_id), "extension": extension},
            initiated_by_user_id=actor.id,
            run_after=datetime.now(UTC) + timedelta(minutes=5),
        )
    await db.commit()
    return reservation
