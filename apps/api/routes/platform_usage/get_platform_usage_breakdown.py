# apps/api/routes/platform_usage/get_platform_usage_breakdown.py

"""Route for a platform-wide AI usage breakdown."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from core.dependencies import MaintenanceAsyncDbSessionDep
from services.ai_usage import get_platform_usage_breakdown
from services.ai_usage.schemas import PlatformUsageBreakdownResponse, PlatformUsageDimension

router = APIRouter()


@router.get("/breakdown")
async def read_platform_usage_breakdown(
    db: MaintenanceAsyncDbSessionDep,
    dimension: Annotated[PlatformUsageDimension, Query()],
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
) -> PlatformUsageBreakdownResponse:
    return await get_platform_usage_breakdown(db, dimension=dimension, from_=from_, to=to)
