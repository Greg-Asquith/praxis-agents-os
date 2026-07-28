# apps/api/routes/artifact_serving/__init__.py

"""Cookie-free artifact serving route registry."""

from fastapi import APIRouter

from routes.artifact_serving.view_artifact_version import router as view_router

router = APIRouter(prefix="/artifacts", include_in_schema=False)
router.include_router(view_router)

__all__ = ["router"]
