# apps/api/services/ai_usage/get_usage_breakdown.py

"""Build one workspace usage breakdown from UTC daily ledger buckets."""

from collections import defaultdict
from datetime import datetime
from uuid import UUID

from sqlalchemy import Date, String, case, cast, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import Agent
from models.ai_usage_event import AIUsageEvent
from models.user import User
from services.ai_usage.pricing import find_price
from services.ai_usage.schemas import (
    BreakdownUsageRow,
    UsageBreakdownResponse,
    UsageDimension,
)
from services.ai_usage.utils import (
    UsageBucket,
    decimal_share,
    fold_buckets,
    optional_cost_share,
    pricing_coverage,
    resolve_usage_range,
)


async def get_usage_breakdown(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    dimension: UsageDimension,
    from_: datetime | None = None,
    to: datetime | None = None,
) -> UsageBreakdownResponse:
    """Return an exact breakdown for one supported attribution dimension."""
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
            AIUsageEvent.workspace_id == workspace_id,
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
    result = await db.execute(statement)
    buckets = [
        UsageBucket(
            day=row.day,
            provider=row.provider,
            model=row.model,
            key=row.dimension_key,
            label=row.dimension_label,
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
    priced = [(bucket, find_price(bucket.provider, bucket.model, bucket.day)) for bucket in buckets]
    total = fold_buckets(priced)
    grouped: dict[tuple[str, str], list] = defaultdict(list)
    for bucket, price in priced:
        grouped[(bucket.key or "unattributed", bucket.label or "Unattributed")].append(
            (bucket, price)
        )

    rows = []
    for (row_key, row_label), grouped_buckets in grouped.items():
        folded = fold_buckets(grouped_buckets)
        rows.append(
            BreakdownUsageRow(
                key=row_key,
                label=row_label,
                estimated_cost_usd=(
                    folded.estimated_cost_usd if folded.has_priced_bucket else None
                ),
                tokens_by_class=folded.tokens_by_class,
                requests=folded.requests,
                token_share=decimal_share(folded.tokens, total.tokens),
                priced_cost_share=(
                    optional_cost_share(folded.estimated_cost_usd, total.estimated_cost_usd)
                    if folded.has_priced_bucket
                    else None
                ),
                pricing_coverage=pricing_coverage(folded),
            )
        )
    rows.sort(
        key=lambda row: (
            row.estimated_cost_usd is not None,
            row.estimated_cost_usd or 0,
            sum(row.tokens_by_class.model_dump().values()),
        ),
        reverse=True,
    )
    return UsageBreakdownResponse(
        from_=usage_range.from_,
        to=usage_range.to,
        dimension=dimension,
        rows=rows,
    )


def _dimension_expressions(dimension: UsageDimension):
    if dimension is UsageDimension.AGENT:
        key = case(
            (AIUsageEvent.agent_id.is_(None), literal("unattributed")),
            else_=cast(AIUsageEvent.agent_id, String),
        )
        label = case(
            (AIUsageEvent.agent_id.is_(None), literal("Unattributed")),
            (Agent.deleted.is_(True), literal("Removed agent")),
            else_=Agent.name,
        )
        return key, label, ((Agent, Agent.id == AIUsageEvent.agent_id),)
    if dimension is UsageDimension.USER:
        key = case(
            (AIUsageEvent.user_id.is_(None), literal("unattributed")),
            else_=cast(AIUsageEvent.user_id, String),
        )
        label = case(
            (AIUsageEvent.user_id.is_(None), literal("Unattributed")),
            (User.deleted.is_(True), literal("Removed user")),
            else_=func.coalesce(User.display_name, cast(User.email, String)),
        )
        return key, label, ((User, User.id == AIUsageEvent.user_id),)
    if dimension is UsageDimension.PURPOSE:
        return AIUsageEvent.purpose, AIUsageEvent.purpose, ()
    return (
        func.concat(AIUsageEvent.provider, ":", AIUsageEvent.model),
        AIUsageEvent.model,
        (),
    )
