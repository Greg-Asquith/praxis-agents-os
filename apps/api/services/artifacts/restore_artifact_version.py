# apps/api/services/artifacts/restore_artifact_version.py

"""Restore a prior artifact version by appending an immutable revision."""

from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from models.artifacts import Artifact, ArtifactRevision
from models.user import User
from models.workspace import Workspace
from services.artifacts.utils import (
    artifact_revision_object_key,
    artifact_revision_ref,
    get_artifact_revision,
    get_artifact_row,
)
from services.storage.errors import StorageNotFoundError
from services.storage.factory import get_storage_provider
from services.storage.utils import put_new_object_with_cleanup


async def restore_artifact_version(
    db: AsyncSession,
    *,
    workspace: Workspace,
    artifact_id: UUID,
    version_id: UUID,
    actor: User,
) -> tuple[Artifact, ArtifactRevision]:
    artifact = await get_artifact_row(
        db,
        workspace_id=workspace.id,
        artifact_id=artifact_id,
        for_update=True,
    )
    source = await get_artifact_revision(db, artifact=artifact, version_id=version_id)
    if artifact.current_version_id is None:
        raise RuntimeError("Artifact has no current revision")
    current = await get_artifact_revision(
        db,
        artifact=artifact,
        version_id=artifact.current_version_id,
    )
    revision_id = uuid4()
    object_key = artifact_revision_object_key(
        workspace.id,
        artifact.id,
        revision_id,
        source.extension,
    )
    provider = get_storage_provider()
    try:
        content = await provider.get_object(artifact_revision_ref(source.object_key))
    except StorageNotFoundError as exc:
        from core.exceptions.general import NotFoundError

        raise NotFoundError("Artifact not found") from exc

    revision = ArtifactRevision(
        id=revision_id,
        artifact_id=artifact.id,
        workspace_id=workspace.id,
        revision_number=current.revision_number + 1,
        revision_kind="restore",
        content_type=source.content_type,
        extension=source.extension,
        size_bytes=source.size_bytes,
        content_hash=source.content_hash,
        object_key=object_key,
        created_by_user_id=actor.id,
        created_by_system=False,
        restored_from_revision_id=source.id,
    )
    db.add(revision)
    await db.flush()
    artifact.current_version_id = revision.id
    await db.flush()
    await put_new_object_with_cleanup(
        provider,
        artifact_revision_ref(object_key),
        content,
        content_type=source.content_type,
    )
    await db.refresh(artifact)
    return artifact, revision
