# apps/api/services/ai_usage/platform_queries.py

"""Read-only cross-workspace AI usage queries for platform operators."""

from datetime import datetime

from sqlalchemy import Date, String, case, cast, func, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.ai_usage_event import AIUsageEvent
from models.user import User
from models.workspace import Workspace
from services.ai_usage.schemas import (
    PlatformUsageBreakdownResponse,
    PlatformUsageDimension,
    UsageSummaryResponse,
)
from services.ai_usage.utils import (
    UsageBucket,
    build_usage_breakdown_rows,
    build_usage_summary_response,
    resolve_usage_range,
)


async def get_platform_usage_summary(
    db: AsyncSession,
    *,
    from_: datetime | None = None,
    to: datetime | None = None,
) -> UsageSummaryResponse:
    """Return exact priced-subset totals across every workspace."""
    await db.execute(text("SET TRANSACTION READ ONLY"))
    usage_range = resolve_usage_range(from_, to)
    day = cast(func.date_trunc("day", func.timezone("UTC", AIUsageEvent.occurred_at)), Date)
    image_model = AIUsageEvent.details["image_model"].astext
    image_quality = AIUsageEvent.details["image_quality"].astext
    image_size = AIUsageEvent.details["image_size"].astext
    statement = (
        select(
            day.label("day"),
            AIUsageEvent.provider,
            AIUsageEvent.model,
            AIUsageEvent.purpose,
            image_model.label("image_model"),
            image_quality.label("image_quality"),
            image_size.label("image_size"),
            func.count(AIUsageEvent.id).label("invocations"),
            func.sum(AIUsageEvent.input_tokens).label("input_tokens"),
            func.sum(AIUsageEvent.cache_read_tokens).label("cache_read_tokens"),
            func.sum(AIUsageEvent.cache_write_tokens).label("cache_write_tokens"),
            func.sum(AIUsageEvent.output_tokens).label("output_tokens"),
            func.sum(AIUsageEvent.requests).label("requests"),
        )
        .where(
            AIUsageEvent.occurred_at >= usage_range.from_,
            AIUsageEvent.occurred_at < usage_range.to,
        )
        .group_by(
            day,
            AIUsageEvent.provider,
            AIUsageEvent.model,
            AIUsageEvent.purpose,
            image_model,
            image_quality,
            image_size,
        )
        .order_by(day, AIUsageEvent.provider, AIUsageEvent.model)
    )
    buckets = _rows_to_buckets(await db.execute(statement))
    return build_usage_summary_response(buckets, usage_range)


async def get_platform_usage_breakdown(
    db: AsyncSession,
    *,
    dimension: PlatformUsageDimension,
    from_: datetime | None = None,
    to: datetime | None = None,
) -> PlatformUsageBreakdownResponse:
    """Return an exact cross-workspace attribution breakdown."""
    await db.execute(text("SET TRANSACTION READ ONLY"))
    usage_range = resolve_usage_range(from_, to)
    day = cast(func.date_trunc("day", func.timezone("UTC", AIUsageEvent.occurred_at)), Date)
    image_model = AIUsageEvent.details["image_model"].astext
    image_quality = AIUsageEvent.details["image_quality"].astext
    image_size = AIUsageEvent.details["image_size"].astext
    key, label, joins = _dimension_expressions(dimension)
    statement = select(
        day.label("day"),
        AIUsageEvent.provider,
        AIUsageEvent.model,
        AIUsageEvent.purpose,
        image_model.label("image_model"),
        image_quality.label("image_quality"),
        image_size.label("image_size"),
        key.label("dimension_key"),
        label.label("dimension_label"),
        func.sum(AIUsageEvent.input_tokens).label("input_tokens"),
        func.sum(AIUsageEvent.cache_read_tokens).label("cache_read_tokens"),
        func.sum(AIUsageEvent.cache_write_tokens).label("cache_write_tokens"),
        func.sum(AIUsageEvent.output_tokens).label("output_tokens"),
        func.sum(AIUsageEvent.requests).label("requests"),
        func.count(AIUsageEvent.id).label("invocations"),
    )
    for target, condition in joins:
        statement = statement.outerjoin(target, condition)
    statement = (
        statement.where(
            AIUsageEvent.occurred_at >= usage_range.from_,
            AIUsageEvent.occurred_at < usage_range.to,
        )
        .group_by(
            day,
            AIUsageEvent.provider,
            AIUsageEvent.model,
            AIUsageEvent.purpose,
            image_model,
            image_quality,
            image_size,
            key,
            label,
        )
        .order_by(day, key, AIUsageEvent.provider, AIUsageEvent.model)
    )
    buckets = _rows_to_buckets(await db.execute(statement), include_dimension=True)
    return PlatformUsageBreakdownResponse(
        from_=usage_range.from_,
        to=usage_range.to,
        dimension=dimension,
        rows=build_usage_breakdown_rows(buckets),
    )


def _rows_to_buckets(result, *, include_dimension: bool = False) -> list[UsageBucket]:
    return [
        UsageBucket(
            day=row.day,
            provider=row.provider,
            model=row.model,
            key=row.dimension_key if include_dimension else None,
            label=row.dimension_label if include_dimension else None,
            input_tokens=int(row.input_tokens or 0),
            cache_read_tokens=int(row.cache_read_tokens or 0),
            cache_write_tokens=int(row.cache_write_tokens or 0),
            output_tokens=int(row.output_tokens or 0),
            requests=int(row.requests or 0),
            invocations=int(row.invocations or 0),
            purpose=row.purpose,
            image_model=row.image_model,
            image_quality=row.image_quality,
            image_size=row.image_size,
        )
        for row in result
    ]


def _dimension_expressions(dimension: PlatformUsageDimension):
    if dimension is PlatformUsageDimension.WORKSPACE:
        key = case(
            (AIUsageEvent.workspace_id.is_(None), literal("unattributed")),
            else_=cast(AIUsageEvent.workspace_id, String),
        )
        label = case(
            (AIUsageEvent.workspace_id.is_(None), literal("Unattributed")),
            (Workspace.deleted.is_(True), literal("Removed workspace")),
            else_=func.concat(Workspace.name, " · ", Workspace.slug),
        )
        return key, label, ((Workspace, Workspace.id == AIUsageEvent.workspace_id),)
    if dimension is PlatformUsageDimension.USER:
        key = case(
            (AIUsageEvent.user_id.is_(None), literal("unattributed")),
            else_=cast(AIUsageEvent.user_id, String),
        )
        label = case(
            (AIUsageEvent.user_id.is_(None), literal("Unattributed")),
            (User.deleted.is_(True), literal("Removed user")),
            (
                User.display_name.is_not(None),
                func.concat(User.display_name, " · ", cast(User.email, String)),
            ),
            else_=cast(User.email, String),
        )
        return key, label, ((User, User.id == AIUsageEvent.user_id),)
    if dimension is PlatformUsageDimension.PURPOSE:
        return AIUsageEvent.purpose, AIUsageEvent.purpose, ()
    return (
        func.concat(AIUsageEvent.provider, ":", AIUsageEvent.model),
        AIUsageEvent.model,
        (),
    )
