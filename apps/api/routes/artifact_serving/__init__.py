# apps/api/routes/artifact_serving/__init__.py

"""Cookie-free artifact serving route registry."""

from fastapi import APIRouter

from routes.artifact_serving.serve_shared_artifact import router as shared_router
from routes.artifact_serving.view_artifact_version import router as view_router

router = APIRouter(prefix="/artifacts", include_in_schema=False)
router.include_router(view_router)
router.include_router(shared_router)

__all__ = ["router"]
