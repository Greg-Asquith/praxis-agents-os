# apps/api/routes/artifact_serving/view_artifact_version.py

"""Serve a signed artifact capability without authentication cookies."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query, Response

from core.dependencies import AsyncDbSessionDep
from services.artifacts.create_view_url import require_valid_artifact_view_signature
from services.artifacts.serve_artifact_version import serve_artifact_version
from services.artifacts.utils import get_artifact_for_serving

router = APIRouter()


@router.get("/view/{artifact_id}/{version_id}")
async def view_artifact_version(
    artifact_id: Annotated[UUID, Path()],
    version_id: Annotated[UUID, Path()],
    expires: Annotated[int, Query()],
    sig: Annotated[str, Query(min_length=1)],
    db: AsyncDbSessionDep,
    download: Annotated[bool, Query()] = False,
) -> Response:
    require_valid_artifact_view_signature(
        artifact_id=artifact_id,
        version_id=version_id,
        expires=expires,
        signature=sig,
    )
    artifact = await get_artifact_for_serving(db, artifact_id=artifact_id)
    return await serve_artifact_version(
        db,
        artifact=artifact,
        version_id=version_id,
        download=download,
    )
