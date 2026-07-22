# apps/api/routes/meta/__init__.py

"""Authenticated application metadata routes."""

from fastapi import APIRouter

from routes.meta.get_openapi_schema import router as get_openapi_schema_router

router = APIRouter(prefix="/meta", tags=["meta"])
router.include_router(get_openapi_schema_router)

__all__ = ["router"]
