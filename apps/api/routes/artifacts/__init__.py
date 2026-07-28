# apps/api/routes/artifacts/__init__.py

"""Artifact management route registry."""

from fastapi import APIRouter, Depends

from core.dependencies import require_read
from routes.artifacts.create_view_url import router as create_view_url_router
from routes.artifacts.get_artifact import router as get_artifact_router
from routes.artifacts.get_version_content import router as get_version_content_router
from routes.artifacts.list_artifacts import router as list_artifacts_router

router = APIRouter(
    prefix="/artifacts",
    tags=["artifacts"],
    dependencies=[Depends(require_read)],
)
router.include_router(list_artifacts_router)
router.include_router(get_version_content_router)
router.include_router(create_view_url_router)
router.include_router(get_artifact_router)

__all__ = ["router"]
