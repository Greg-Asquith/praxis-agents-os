# apps/api/services/artifacts/utils.py

"""Shared artifact service helpers."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, NotFoundError
from core.rate_limiting import build_rate_limit_error, rate_limiter
from core.settings import settings
from models.artifacts import Artifact, ArtifactRevision
from services.artifacts.domain import CREATABLE_ARTIFACT_TYPES
from services.artifacts.schemas import ArtifactRead, ArtifactSummaryRead, ArtifactVersionRead
from services.storage.domain import StorageBucket, StorageObjectRef, make_storage_object_ref
from utils.digests import sha256_hex


@dataclass(frozen=True)
class ArtifactRevisionActor:
    """Exactly one actor for an immutable artifact revision."""

    user_id: UUID | None = None
    agent_id: UUID | None = None
    system: bool = False

    def columns(self) -> dict[str, UUID | bool | None]:
        if sum((self.user_id is not None, self.agent_id is not None, self.system)) != 1:
            raise AppValidationError("An artifact revision requires exactly one actor")
        return {
            "created_by_user_id": self.user_id,
            "created_by_agent_id": self.agent_id,
            "created_by_system": self.system,
        }


def artifact_revision_object_key(
    workspace_id: UUID,
    artifact_id: UUID,
    revision_id: UUID,
    extension: str,
) -> str:
    """Build the private storage key for one artifact revision."""
    normalized_extension = extension.strip().lower()
    if not normalized_extension.startswith("."):
        normalized_extension = f".{normalized_extension}"
    return f"workspaces/{workspace_id}/artifacts/{artifact_id}/{revision_id}{normalized_extension}"


def artifact_revision_ref(object_key: str) -> StorageObjectRef:
    """Return a private storage reference for an artifact revision."""
    return make_storage_object_ref(StorageBucket.PRIVATE, object_key)


def artifact_content_hash(content: bytes) -> str:
    """Return the lowercase SHA-256 digest for artifact content."""
    return sha256_hex(content)


async def check_workspace_share_rate_limit(
    db: AsyncSession,
    *,
    workspace_id: UUID,
) -> None:
    """Apply the governance creation limit through the existing IP-keyed store."""
    result = await rate_limiter.check_rate_limit(
        ip="0.0.0.0",  # noqa: S104 - documented sentinel for a workspace subject key
        endpoint=f"artifact_share_create:{workspace_id}",
        limit_type="artifact_share_creation",
        custom_limit=10,
        custom_window=3600,
        db=db,
    )
    if not result.allowed:
        raise build_rate_limit_error(result, limit_type="artifact_share_creation")


def validate_artifact_content(*, artifact_type: str, title: str, content: str) -> bytes:
    if artifact_type not in CREATABLE_ARTIFACT_TYPES:
        raise AppValidationError("Unsupported artifact type", field="artifact_type")
    if not title.strip() or len(title.strip()) > 255:
        raise AppValidationError(
            "Artifact title must be between 1 and 255 characters", field="title"
        )
    data = content.encode("utf-8")
    if len(data) > settings.ARTIFACT_MAX_CONTENT_BYTES:
        raise AppValidationError(
            "Artifact content is too large",
            field="content",
            details={
                "max_bytes": settings.ARTIFACT_MAX_CONTENT_BYTES,
                "content_bytes": len(data),
            },
        )
    return data


async def get_artifact_row(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    artifact_id: UUID,
    for_update: bool = False,
) -> Artifact:
    stmt = select(Artifact).where(
        Artifact.id == artifact_id,
        Artifact.workspace_id == workspace_id,
        Artifact.deleted.is_(False),
    )
    if for_update:
        stmt = stmt.with_for_update()
    artifact = await db.scalar(stmt)
    if artifact is None:
        raise NotFoundError("Artifact not found", resource_type="artifact")
    return artifact


async def get_artifact_for_serving(
    db: AsyncSession,
    *,
    artifact_id: UUID,
) -> Artifact:
    artifact = await db.scalar(
        select(Artifact).where(
            Artifact.id == artifact_id,
            Artifact.deleted.is_(False),
        )
    )
    if artifact is None:
        raise NotFoundError("Artifact not found")
    return artifact


async def get_artifact_revision(
    db: AsyncSession,
    *,
    artifact: Artifact | ArtifactRead,
    version_id: UUID,
) -> ArtifactRevision:
    revision = await db.scalar(
        select(ArtifactRevision).where(
            ArtifactRevision.id == version_id,
            ArtifactRevision.artifact_id == artifact.id,
            ArtifactRevision.workspace_id == artifact.workspace_id,
        )
    )
    if revision is None:
        raise NotFoundError("Artifact not found", resource_type="artifact")
    return revision


def artifact_to_summary(artifact: Artifact, *, version_count: int) -> ArtifactSummaryRead:
    if artifact.current_version_id is None:
        raise RuntimeError("Artifact has no current revision")
    return ArtifactSummaryRead(
        id=artifact.id,
        workspace_id=artifact.workspace_id,
        agent_id=artifact.agent_id,
        conversation_id=artifact.conversation_id,
        run_id=artifact.run_id,
        current_version_id=artifact.current_version_id,
        artifact_type=artifact.artifact_type,
        title=artifact.title,
        created_at=artifact.created_at,
        updated_at=artifact.updated_at,
        version_count=version_count,
    )


def artifact_to_read(
    artifact: Artifact,
    revisions: list[ArtifactRevision],
) -> ArtifactRead:
    if artifact.current_version_id is None:
        raise RuntimeError("Artifact has no current revision")
    return ArtifactRead(
        id=artifact.id,
        workspace_id=artifact.workspace_id,
        agent_id=artifact.agent_id,
        conversation_id=artifact.conversation_id,
        run_id=artifact.run_id,
        current_version_id=artifact.current_version_id,
        artifact_type=artifact.artifact_type,
        title=artifact.title,
        created_at=artifact.created_at,
        updated_at=artifact.updated_at,
        versions=[
            ArtifactVersionRead(
                id=revision.id,
                created_at=revision.created_at,
                created_by_user_id=revision.created_by_user_id,
                created_by_agent_id=revision.created_by_agent_id,
                created_by_system=revision.created_by_system,
                size_bytes=revision.size_bytes,
                revision_number=revision.revision_number,
                revision_kind=revision.revision_kind,
                restored_from_revision_id=revision.restored_from_revision_id,
            )
            for revision in revisions
        ],
    )
