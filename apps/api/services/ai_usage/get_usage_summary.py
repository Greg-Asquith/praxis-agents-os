# apps/api/services/ai_usage/get_usage_summary.py

"""Build one workspace usage summary from UTC daily ledger buckets."""

from collections import defaultdict
from datetime import datetime
from uuid import UUID

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.ai_usage_event import AIUsageEvent
from services.ai_usage.pricing import find_price
from services.ai_usage.schemas import (
    DailyUsagePoint,
    ModelUsageRow,
    UsageSummaryResponse,
    UsageTotals,
)
from services.ai_usage.utils import (
    UsageBucket,
    decimal_share,
    fold_buckets,
    optional_cost_share,
    pricing_coverage,
    resolve_usage_range,
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
            image_model=row.image_model,
            image_quality=row.image_quality,
            image_size=row.image_size,
        )
        for row in result
    ]
    priced = [(bucket, find_price(bucket.provider, bucket.model, bucket.day)) for bucket in buckets]
    total = fold_buckets(priced)

    daily_buckets: dict[object, list] = defaultdict(list)
    model_buckets: dict[tuple[str, str], list] = defaultdict(list)
    for bucket, price in priced:
        daily_buckets[bucket.day].append((bucket, price))
        model_buckets[(bucket.provider, bucket.model)].append((bucket, price))

    daily = []
    for bucket_day, day_buckets in daily_buckets.items():
        folded = fold_buckets(day_buckets)
        daily.append(
            DailyUsagePoint(
                date=bucket_day,
                estimated_cost_usd=folded.estimated_cost_usd,
                tokens=folded.tokens,
                requests=folded.requests,
            )
        )

    models = []
    for (provider, model), grouped_buckets in model_buckets.items():
        folded = fold_buckets(grouped_buckets)
        models.append(
            ModelUsageRow(
                provider=provider,
                model=model,
                estimated_cost_usd=(
                    folded.estimated_cost_usd if folded.has_priced_bucket else None
                ),
                tokens=folded.tokens,
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
    models.sort(
        key=lambda row: (
            row.estimated_cost_usd is not None,
            row.estimated_cost_usd or 0,
            row.tokens,
        ),
        reverse=True,
    )

    return UsageSummaryResponse(
        from_=usage_range.from_,
        to=usage_range.to,
        totals=UsageTotals(
            estimated_cost_usd=total.estimated_cost_usd,
            tokens_by_class=total.tokens_by_class,
            requests=total.requests,
        ),
        pricing_coverage=pricing_coverage(total),
        daily=daily,
        models=models,
    )
