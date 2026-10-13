# apps/api/services/ai_usage/get_usage_summary.py

"""Build one workspace usage summary from UTC daily ledger buckets."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.ai_usage_event import AIUsageEvent
from services.ai_usage.schemas import UsageSummaryResponse
from services.ai_usage.utils import (
    UsageBucket,
    build_usage_summary_response,
    output_price_columns,
    output_price_values,
    resolve_usage_range,
    video_output_seconds_column,
)


async def get_usage_summary(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    from_: datetime | None = None,
    to: datetime | None = None,
) -> UsageSummaryResponse:
    """Return exact priced-subset totals and coverage for one workspace."""
    usage_range = resolve_usage_range(from_, to)
    day = cast(func.date_trunc("day", func.timezone("UTC", AIUsageEvent.occurred_at)), Date)
    price_columns = output_price_columns()
    statement = (
        select(
            day.label("day"),
            AIUsageEvent.provider,
            AIUsageEvent.model,
            AIUsageEvent.purpose,
            *price_columns,
            video_output_seconds_column(),
            func.count(AIUsageEvent.id).label("invocations"),
            func.sum(AIUsageEvent.input_tokens).label("input_tokens"),
            func.sum(AIUsageEvent.cache_read_tokens).label("cache_read_tokens"),
            func.sum(AIUsageEvent.cache_write_tokens).label("cache_write_tokens"),
            func.sum(AIUsageEvent.output_tokens).label("output_tokens"),
            func.sum(AIUsageEvent.requests).label("requests"),
        )
        .where(
            AIUsageEvent.workspace_id == workspace_id,
            AIUsageEvent.occurred_at >= usage_range.from_,
            AIUsageEvent.occurred_at < usage_range.to,
        )
        .group_by(
            day,
            AIUsageEvent.provider,
            AIUsageEvent.model,
            AIUsageEvent.purpose,
            *price_columns,
        )
        .order_by(day, AIUsageEvent.provider, AIUsageEvent.model)
    )
    result = await db.execute(statement)
    buckets = [
        UsageBucket(
            day=row.day,
            provider=row.provider,
            model=row.model,
            input_tokens=int(row.input_tokens or 0),
            cache_read_tokens=int(row.cache_read_tokens or 0),
            cache_write_tokens=int(row.cache_write_tokens or 0),
            output_tokens=int(row.output_tokens or 0),
            requests=int(row.requests or 0),
            invocations=int(row.invocations or 0),
            purpose=row.purpose,
            **output_price_values(row),
        )
        for row in result
    ]
    return build_usage_summary_response(buckets, usage_range)
