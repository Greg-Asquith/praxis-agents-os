# apps/api/routes/platform_usage/__init__.py

"""Platform-wide AI usage route registry."""

from fastapi import APIRouter, Depends

from core.dependencies import require_super_admin
from routes.platform_usage.get_platform_usage_breakdown import router as breakdown_router
from routes.platform_usage.get_platform_usage_summary import router as summary_router

router = APIRouter(
    prefix="/platform-usage",
    tags=["platform-usage"],
    dependencies=[Depends(require_super_admin)],
)
router.include_router(summary_router)
router.include_router(breakdown_router)

__all__ = ["router"]
