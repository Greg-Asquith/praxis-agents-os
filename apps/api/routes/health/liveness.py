# apps/api/routes/health/liveness.py

"""Dependency-free process liveness."""

from fastapi import APIRouter

from core.settings import settings
from routes.health.domain import LivenessResponse

router = APIRouter()


@router.get("/healthz", include_in_schema=False)
def get_liveness() -> LivenessResponse:
    return LivenessResponse(version=settings.APP_VERSION)
