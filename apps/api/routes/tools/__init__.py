# apps/api/routes/tools/__init__.py

"""Runtime tool catalog route registry."""

from fastapi import APIRouter

from routes.tools.list_catalog import router as list_catalog_router

router = APIRouter(prefix="/tools", tags=["tools"])
router.include_router(list_catalog_router)

__all__ = ["router"]
