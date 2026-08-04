# apps/api/routes/artifact_serving/serve_shared_artifact.py

"""Serve one version-pinned anonymous artifact share."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response

from core.dependencies import MaintenanceAsyncDbSessionDep
from core.exceptions.general import NotFoundError
from core.rate_limiting import require_rate_limit
from core.settings import settings
from services.artifacts import resolve_artifact_share, serve_artifact_version

router = APIRouter()
AnonymousShareRateLimitDep = Annotated[
    None,
    Depends(require_rate_limit(custom_limit=120, custom_window=3600)),
]


@router.get("/shared/{token}")
async def serve_shared_artifact(
    request: Request,
    token: str,
    _: AnonymousShareRateLimitDep,
    db: MaintenanceAsyncDbSessionDep,
    download: Annotated[bool, Query()] = False,
) -> Response:
    if not settings.ARTIFACT_SHARING_ENABLED or not 32 <= len(token) <= 64:
        raise NotFoundError("Share not found")
    share, artifact = await resolve_artifact_share(db, token=token, request=request)
    return await serve_artifact_version(
        db,
        artifact=artifact,
        version_id=share.version_id,
        download=download,
    )
