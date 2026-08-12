# apps/api/routes/status/__init__.py

"""Status route registry."""

from fastapi import APIRouter, Depends

from core.dependencies import require_read
from routes.status.get_summary import router as get_summary_router

router = APIRouter(
    prefix="/status",
    tags=["status"],
    dependencies=[Depends(require_read)],
)
router.include_router(get_summary_router)

__all__ = ["router"]
