# apps/api/services/artifacts/get_version_content.py

"""Read artifact revision content for authenticated management surfaces."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.artifacts import Artifact
from services.artifacts.schemas import ArtifactRead, ArtifactVersionContentRead
from services.artifacts.utils import artifact_revision_ref, get_artifact_revision
from services.storage.factory import get_storage_provider


async def get_version_content(
    db: AsyncSession,
    *,
    artifact: Artifact | ArtifactRead,
    version_id: UUID,
) -> ArtifactVersionContentRead:
    revision = await get_artifact_revision(db, artifact=artifact, version_id=version_id)
    provider = get_storage_provider()
    ref = artifact_revision_ref(revision.object_key)
    if artifact.artifact_type == "image-ref":
        signed = await provider.create_signed_download(
            ref,
            expires_in=timedelta(minutes=5),
            filename=f"{artifact.title}{revision.extension}",
        )
        return ArtifactVersionContentRead(
            content_type=revision.content_type,
            size_bytes=revision.size_bytes,
            download_url=signed.url,
        )
    return ArtifactVersionContentRead(
        content=(await provider.get_object(ref)).decode("utf-8"),
        content_type=revision.content_type,
        size_bytes=revision.size_bytes,
    )
