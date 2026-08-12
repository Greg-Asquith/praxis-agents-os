# apps/api/services/ai_usage/schemas.py

"""Pydantic contracts for workspace AI usage reads."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class UsageDimension(StrEnum):
    AGENT = "agent"
    USER = "user"
    PURPOSE = "purpose"
    MODEL = "model"


class TokenCounts(BaseModel):
    input: int = 0
    cache_read: int = 0
    cache_write: int = 0
    output: int = 0


class PricingCoverage(BaseModel):
    priced_tokens: int
    unpriced_tokens: int
    token_coverage_percent: Decimal
    priced_requests: int
    unpriced_requests: int
    request_coverage_percent: Decimal
    priced_image_generations: int = 0
    unpriced_image_generations: int = 0


class UsageTotals(BaseModel):
    estimated_cost_usd: Decimal
    tokens_by_class: TokenCounts
    requests: int


class DailyUsagePoint(BaseModel):
    date: date
    estimated_cost_usd: Decimal
    tokens: int
    requests: int


class ModelUsageRow(BaseModel):
    provider: str
    model: str
    estimated_cost_usd: Decimal | None
    tokens: int
    requests: int
    token_share: Decimal
    priced_cost_share: Decimal | None
    pricing_coverage: PricingCoverage


class UsageSummaryResponse(BaseModel):
    from_: datetime = Field(alias="from")
    to: datetime
    timezone: str = "UTC"
    totals: UsageTotals
    pricing_coverage: PricingCoverage
    daily: list[DailyUsagePoint]
    models: list[ModelUsageRow]

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class BreakdownUsageRow(BaseModel):
    key: str
    label: str
    estimated_cost_usd: Decimal | None
    tokens_by_class: TokenCounts
    requests: int
    token_share: Decimal
    priced_cost_share: Decimal | None
    pricing_coverage: PricingCoverage


class UsageBreakdownResponse(BaseModel):
    from_: datetime = Field(alias="from")
    to: datetime
    timezone: str = "UTC"
    dimension: UsageDimension
    rows: list[BreakdownUsageRow]

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)
