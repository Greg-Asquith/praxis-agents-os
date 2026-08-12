# apps/api/routes/usage/get_usage_breakdown.py

"""Route for a workspace AI usage breakdown."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from core.dependencies import AsyncDbSessionDep, CurrentWorkspaceDep
from services.ai_usage import get_usage_breakdown
from services.ai_usage.schemas import UsageBreakdownResponse, UsageDimension

router = APIRouter()


@router.get("/breakdown")
async def read_usage_breakdown(
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
    dimension: Annotated[UsageDimension, Query()],
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
) -> UsageBreakdownResponse:
    workspace, _membership = workspace_context
    return await get_usage_breakdown(
        db,
        workspace_id=workspace.id,
        dimension=dimension,
        from_=from_,
        to=to,
    )
