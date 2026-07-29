# apps/api/routes/health/__init__.py

"""Operational health route composition."""

from fastapi import APIRouter

from routes.health.liveness import router as liveness_router
from routes.health.readiness import router as readiness_router

router = APIRouter(tags=["health"])
router.include_router(liveness_router)
router.include_router(readiness_router)

__all__ = ["router"]
