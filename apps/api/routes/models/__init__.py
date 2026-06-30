# apps/api/routes/models/__init__.py

"""Model catalog route registry."""

from fastapi import APIRouter

from routes.models.list_catalog import router as list_catalog_router

router = APIRouter(prefix="/models", tags=["models"])
router.include_router(list_catalog_router)

__all__ = ["router"]
