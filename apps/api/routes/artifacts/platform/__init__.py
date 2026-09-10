# apps/api/routes/artifacts/platform/__init__.py

"""Composes platform Artifact management routes."""

from fastapi import APIRouter

from routes.artifacts.platform.create_artifact import router as create_artifact_router
from routes.artifacts.platform.delete_artifact import router as delete_artifact_router
from routes.artifacts.platform.get_artifact import router as get_artifact_router
from routes.artifacts.platform.get_version_content import router as get_version_content_router
from routes.artifacts.platform.list_artifacts import router as list_artifacts_router
from routes.artifacts.platform.publish_artifact import router as publish_artifact_router
from routes.artifacts.platform.restore_artifact_version import (
    router as restore_artifact_version_router,
)
from routes.artifacts.platform.update_artifact import router as update_artifact_router
from routes.artifacts.platform.withdraw_artifact import router as withdraw_artifact_router

router = APIRouter(prefix="/platform")
router.include_router(create_artifact_router)
router.include_router(update_artifact_router)
router.include_router(restore_artifact_version_router)
router.include_router(publish_artifact_router)
router.include_router(withdraw_artifact_router)
router.include_router(delete_artifact_router)
router.include_router(get_artifact_router)
router.include_router(get_version_content_router)
router.include_router(list_artifacts_router)
