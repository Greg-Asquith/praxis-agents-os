# apps/api/routes/platform_usage/get_platform_usage_summary.py

"""Route for the platform-wide AI usage summary."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from core.dependencies import MaintenanceAsyncDbSessionDep
from services.ai_usage import get_platform_usage_summary
from services.ai_usage.schemas import UsageSummaryResponse

router = APIRouter()


@router.get("/summary")
async def read_platform_usage_summary(
    db: MaintenanceAsyncDbSessionDep,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
) -> UsageSummaryResponse:
    return await get_platform_usage_summary(db, from_=from_, to=to)
