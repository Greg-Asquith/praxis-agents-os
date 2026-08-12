# apps/api/routes/usage/__init__.py

"""Workspace AI usage route registry."""

from fastapi import APIRouter, Depends

from core.dependencies import require_owner
from routes.usage.get_usage_breakdown import router as breakdown_router
from routes.usage.get_usage_summary import router as summary_router

router = APIRouter(
    prefix="/usage",
    tags=["usage"],
    dependencies=[Depends(require_owner)],
)
router.include_router(summary_router)
router.include_router(breakdown_router)

__all__ = ["router"]
