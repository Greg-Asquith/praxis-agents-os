# apps/api/routes/usage/get_usage_summary.py

"""Route for a workspace AI usage summary."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from core.dependencies import AsyncDbSessionDep, CurrentWorkspaceDep
from services.ai_usage import get_usage_summary
from services.ai_usage.schemas import UsageSummaryResponse

router = APIRouter()


@router.get("/summary")
async def read_usage_summary(
    db: AsyncDbSessionDep,
    workspace_context: CurrentWorkspaceDep,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
) -> UsageSummaryResponse:
    workspace, _membership = workspace_context
    return await get_usage_summary(
        db,
        workspace_id=workspace.id,
        from_=from_,
        to=to,
    )
