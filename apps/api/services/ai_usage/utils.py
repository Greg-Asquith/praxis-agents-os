# apps/api/services/ai_usage/utils.py

"""Shared AI usage conversion, persistence, and aggregation mechanics."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from pydantic_ai.messages import ModelResponse
from pydantic_ai.usage import RunUsage
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.ai_usage_event import AIUsageEvent
from services.ai_usage.domain import AIUsageEventData
from services.ai_usage.pricing import ModelPrice, find_image_output_price, find_price
from services.ai_usage.schemas import (
    BreakdownUsageRow,
    DailyUsagePoint,
    ModelUsageRow,
    PricingCoverage,
    TokenCounts,
    UsageSummaryResponse,
    UsageTotals,
)

_MILLION = Decimal(1_000_000)
_HUNDRED = Decimal(100)


@dataclass(frozen=True)
class UsageRange:
    from_: datetime
    to: datetime


@dataclass(frozen=True)
class UsageBucket:
    day: date
    provider: str
    model: str
    input_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    output_tokens: int
    requests: int
    invocations: int = 0
    purpose: str | None = None
    image_model: str | None = None
    image_quality: str | None = None
    image_size: str | None = None
    key: str | None = None
    label: str | None = None

    @property
    def uncached_input_tokens(self) -> int:
        """Return the disjoint input subset after removing cached tokens."""
        return max(0, self.input_tokens - self.cache_read_tokens - self.cache_write_tokens)

    @property
    def tokens(self) -> int:
        return (
            self.uncached_input_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
            + self.output_tokens
        )


@dataclass
class UsageFold:
    tokens_by_class: TokenCounts = field(default_factory=TokenCounts)
    requests: int = 0
    estimated_cost_usd: Decimal = Decimal(0)
    priced_tokens: int = 0
    unpriced_tokens: int = 0
    priced_requests: int = 0
    unpriced_requests: int = 0
    has_priced_bucket: bool = False
    priced_image_generations: int = 0
    unpriced_image_generations: int = 0

    @property
    def tokens(self) -> int:
        return sum(
            (
                self.tokens_by_class.input,
                self.tokens_by_class.cache_read,
                self.tokens_by_class.cache_write,
                self.tokens_by_class.output,
            )
        )


def resolve_usage_range(
    from_: datetime | None,
    to: datetime | None,
    *,
    now: datetime | None = None,
) -> UsageRange:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    end = to or current
    start = from_ or (end - timedelta(days=30))
    if start.tzinfo is None or end.tzinfo is None:
        raise AppValidationError("Usage range timestamps must include a UTC offset.")
    start = start.astimezone(UTC)
    end = end.astimezone(UTC)
    if start >= end:
        raise AppValidationError("Usage range start must be before its end.")
    if end - start > timedelta(days=92):
        raise AppValidationError("Usage range cannot exceed 92 days.")
    return UsageRange(from_=start, to=end)


def bucket_cost(bucket: UsageBucket, price: ModelPrice) -> Decimal:
    return (
        Decimal(bucket.uncached_input_tokens) * price.input_usd_per_mtok
        + Decimal(bucket.cache_read_tokens) * price.cache_read_usd_per_mtok
        + Decimal(bucket.cache_write_tokens) * price.cache_write_usd_per_mtok
        + Decimal(bucket.output_tokens) * price.output_usd_per_mtok
    ) / _MILLION


def fold_buckets(
    buckets: Iterable[tuple[UsageBucket, ModelPrice | None]],
) -> UsageFold:
    folded = UsageFold()
    for bucket, price in buckets:
        folded.tokens_by_class.input += bucket.uncached_input_tokens
        folded.tokens_by_class.cache_read += bucket.cache_read_tokens
        folded.tokens_by_class.cache_write += bucket.cache_write_tokens
        folded.tokens_by_class.output += bucket.output_tokens
        folded.requests += bucket.requests
        if price is None:
            folded.unpriced_tokens += bucket.tokens
            folded.unpriced_requests += bucket.requests
        else:
            folded.has_priced_bucket = True
            folded.priced_tokens += bucket.tokens
            folded.priced_requests += bucket.requests
            folded.estimated_cost_usd += bucket_cost(bucket, price)
        if bucket.purpose == "image_generation":
            image_price = (
                find_image_output_price(
                    bucket.provider,
                    bucket.image_model,
                    bucket.image_quality,
                    bucket.image_size,
                    bucket.day,
                )
                if bucket.image_model and bucket.image_quality and bucket.image_size
                else None
            )
            if image_price is None:
                folded.unpriced_image_generations += bucket.invocations
            else:
                folded.has_priced_bucket = True
                folded.priced_image_generations += bucket.invocations
                folded.estimated_cost_usd += Decimal(bucket.invocations) * image_price.usd_per_image
    return folded


def decimal_share(numerator: int | Decimal, denominator: int | Decimal) -> Decimal:
    if denominator == 0:
        return Decimal(0)
    return Decimal(numerator) / Decimal(denominator)


def optional_cost_share(cost: Decimal, total_cost: Decimal) -> Decimal | None:
    if total_cost == 0:
        return None
    return cost / total_cost


def pricing_coverage(folded: UsageFold) -> PricingCoverage:
    total_tokens = folded.priced_tokens + folded.unpriced_tokens
    total_requests = folded.priced_requests + folded.unpriced_requests
    return PricingCoverage(
        priced_tokens=folded.priced_tokens,
        unpriced_tokens=folded.unpriced_tokens,
        token_coverage_percent=decimal_share(folded.priced_tokens, total_tokens) * _HUNDRED,
        priced_requests=folded.priced_requests,
        unpriced_requests=folded.unpriced_requests,
        request_coverage_percent=decimal_share(folded.priced_requests, total_requests) * _HUNDRED,
        priced_image_generations=folded.priced_image_generations,
        unpriced_image_generations=folded.unpriced_image_generations,
    )


def build_usage_summary_response(
    buckets: list[UsageBucket],
    usage_range: UsageRange,
) -> UsageSummaryResponse:
    """Fold daily pricing buckets into the shared workspace/platform summary."""
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


def build_usage_breakdown_rows(buckets: list[UsageBucket]) -> list[BreakdownUsageRow]:
    """Fold daily pricing buckets into shared workspace/platform breakdown rows."""
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
    return rows


def usage_values(usage: Any) -> dict[str, int]:
    """Return the four token classes and request count from Pydantic AI usage."""
    values: dict[str, int] = {}
    for name in (
        "input_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "output_tokens",
        "requests",
    ):
        raw = getattr(usage, name, 0) or 0
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise ValueError(f"AI usage {name} must be a non-negative integer")
        values[name] = raw
    return values


def subtract_usage(current: RunUsage, baseline: RunUsage) -> dict[str, int]:
    current_values = usage_values(current)
    baseline_values = usage_values(baseline)
    return {name: max(0, value - baseline_values[name]) for name, value in current_values.items()}


def sum_response_usage(messages: list[object]) -> dict[str, int]:
    total = dict.fromkeys(usage_values(RunUsage()), 0)
    for message in messages:
        if not isinstance(message, ModelResponse):
            continue
        response_values = usage_values(message.usage)
        response_values["requests"] = 1
        for name, value in response_values.items():
            total[name] += value
    return total


def add_event(db: AsyncSession, event: AIUsageEventData) -> None:
    db.add(
        AIUsageEvent(
            workspace_id=event.workspace_id,
            provider=event.provider,
            model=event.model,
            purpose=event.purpose,
            input_tokens=event.input_tokens,
            cache_read_tokens=event.cache_read_tokens,
            cache_write_tokens=event.cache_write_tokens,
            output_tokens=event.output_tokens,
            requests=event.requests,
            agent_id=event.agent_id,
            user_id=event.user_id,
            run_id=event.run_id,
            conversation_id=event.conversation_id,
            details=event.details,
        )
    )
