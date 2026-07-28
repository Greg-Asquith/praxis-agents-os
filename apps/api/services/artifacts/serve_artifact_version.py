# apps/api/services/artifacts/serve_artifact_version.py

"""Render one artifact version without depending on its credential type."""

from uuid import UUID

from fastapi import Response
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import NotFoundError
from models.artifacts import Artifact
from services.artifacts.domain import ARTIFACT_CONTENT_TYPES, serving_headers
from services.artifacts.utils import artifact_revision_ref, get_artifact_revision
from services.storage.errors import StorageNotFoundError
from services.storage.factory import get_storage_provider
from services.storage.paths import build_content_disposition


async def serve_artifact_version(
    db: AsyncSession,
    *,
    artifact: Artifact,
    version_id: UUID,
    download: bool = False,
) -> Response:
    revision = await get_artifact_revision(db, artifact=artifact, version_id=version_id)
    provider = get_storage_provider()
    ref = artifact_revision_ref(revision.object_key)
    try:
        stored = await provider.stat_object(ref)
        content = await provider.get_object(ref) if stored is not None else None
    except StorageNotFoundError as exc:
        raise NotFoundError("Artifact not found") from exc
    if stored is None:
        raise NotFoundError("Artifact not found")
    if artifact.artifact_type == "image-ref":
        if not stored.content_type or not stored.content_type.startswith("image/"):
            raise NotFoundError("Artifact not found")
        content_type = stored.content_type
    else:
        content_type = ARTIFACT_CONTENT_TYPES[artifact.artifact_type]
    headers = serving_headers(
        artifact_type=artifact.artifact_type,
        content_type=content_type,
    )
    if download:
        disposition = build_content_disposition(f"{artifact.title}{revision.extension}")
        if disposition:
            headers["Content-Disposition"] = disposition
    return Response(
        content=content,
        headers=headers,
    )
