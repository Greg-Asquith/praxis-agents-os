"""Workspace usage aggregation and exact pricing tests."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError
from models.agent import Agent
from models.ai_usage_event import AIUsageEvent
from services.ai_usage.get_usage_breakdown import get_usage_breakdown
from services.ai_usage.get_usage_summary import get_usage_summary
from services.ai_usage.schemas import UsageDimension
from services.ai_usage.utils import resolve_usage_range
from tests.factories import build_user, build_workspace


def _event(workspace_id, occurred_at, **overrides) -> AIUsageEvent:
    values = {
        "workspace_id": workspace_id,
        "occurred_at": occurred_at,
        "provider": "anthropic",
        "model": "claude-sonnet-5",
        "purpose": "agent_run",
        "input_tokens": 1_000_000,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "output_tokens": 0,
        "requests": 1,
    }
    values.update(overrides)
    return AIUsageEvent(**values)


@pytest.mark.asyncio
async def test_summary_prices_utc_days_before_folding_and_sums_requests(
    db_session: AsyncSession,
) -> None:
    workspace = build_workspace(slug=f"usage-{uuid4().hex}")
    db_session.add(workspace)
    await db_session.flush()
    db_session.add_all(
        [
            _event(
                workspace.id,
                datetime(2026, 8, 31, 23, 59, tzinfo=UTC),
                requests=3,
            ),
            _event(
                workspace.id,
                datetime(2026, 9, 1, 0, 0, tzinfo=UTC),
                requests=2,
            ),
        ]
    )
    await db_session.flush()

    summary = await get_usage_summary(
        db_session,
        workspace_id=workspace.id,
        from_=datetime(2026, 8, 31, tzinfo=UTC),
        to=datetime(2026, 9, 2, tzinfo=UTC),
    )

    assert summary.totals.estimated_cost_usd == Decimal("5")
    assert summary.totals.requests == 5
    assert [point.estimated_cost_usd for point in summary.daily] == [
        Decimal("2"),
        Decimal("3"),
    ]


@pytest.mark.asyncio
async def test_summary_zero_fills_every_utc_day_in_range(db_session: AsyncSession) -> None:
    workspace = build_workspace(slug=f"gaps-{uuid4().hex}")
    db_session.add(workspace)
    await db_session.flush()
    db_session.add_all(
        [
            _event(workspace.id, datetime(2026, 8, 12, 12, tzinfo=UTC), requests=1),
            _event(workspace.id, datetime(2026, 8, 15, 12, tzinfo=UTC), requests=2),
        ]
    )
    await db_session.flush()

    summary = await get_usage_summary(
        db_session,
        workspace_id=workspace.id,
        from_=datetime(2026, 8, 11, 9, 30, tzinfo=UTC),
        to=datetime(2026, 8, 16, 9, 30, tzinfo=UTC),
    )

    assert [str(point.date) for point in summary.daily] == [
        "2026-08-11",
        "2026-08-12",
        "2026-08-13",
        "2026-08-14",
        "2026-08-15",
        "2026-08-16",
    ]
    assert [point.requests for point in summary.daily] == [0, 1, 0, 0, 2, 0]
    assert [point.estimated_cost_usd for point in summary.daily] == [
        Decimal("0"),
        Decimal("2"),
        Decimal("0"),
        Decimal("0"),
        Decimal("2"),
        Decimal("0"),
    ]
    assert summary.totals.requests == 3


@pytest.mark.asyncio
async def test_summary_uses_half_open_range_and_exposes_unpriced_coverage(
    db_session: AsyncSession,
) -> None:
    workspace = build_workspace(slug=f"coverage-{uuid4().hex}")
    db_session.add(workspace)
    await db_session.flush()
    db_session.add_all(
        [
            _event(
                workspace.id,
                datetime(2026, 8, 12, 12, tzinfo=UTC),
                input_tokens=1,
                output_tokens=1,
                requests=4,
            ),
            _event(
                workspace.id,
                datetime(2026, 8, 12, 13, tzinfo=UTC),
                provider="azure",
                model="customer-deployment",
                input_tokens=2,
                output_tokens=0,
                requests=7,
            ),
            _event(
                workspace.id,
                datetime(2026, 8, 13, tzinfo=UTC),
                input_tokens=9_000_000,
                requests=99,
            ),
        ]
    )
    await db_session.flush()

    summary = await get_usage_summary(
        db_session,
        workspace_id=workspace.id,
        from_=datetime(2026, 8, 12, tzinfo=UTC),
        to=datetime(2026, 8, 13, tzinfo=UTC),
    )

    assert summary.totals.estimated_cost_usd == Decimal("0.000012")
    assert summary.totals.requests == 11
    assert summary.pricing_coverage.priced_tokens == 2
    assert summary.pricing_coverage.unpriced_tokens == 2
    assert summary.pricing_coverage.priced_requests == 4
    assert summary.pricing_coverage.unpriced_requests == 7
    unpriced = next(row for row in summary.models if row.provider == "azure")
    assert unpriced.estimated_cost_usd is None
    assert unpriced.priced_cost_share is None


@pytest.mark.asyncio
async def test_summary_reconciles_inclusive_cached_input_with_provider_cost(
    db_session: AsyncSession,
) -> None:
    workspace = build_workspace(slug=f"inclusive-input-{uuid4().hex}")
    db_session.add(workspace)
    await db_session.flush()
    occurred_at = datetime(2026, 8, 13, 12, tzinfo=UTC)
    db_session.add_all(
        [
            _event(
                workspace.id,
                occurred_at,
                provider="openai",
                model="gpt-5.6-luna",
                input_tokens=521_813,
                cache_read_tokens=395_052,
                cache_write_tokens=126_020,
                output_tokens=12_051,
                requests=29,
            ),
            _event(
                workspace.id,
                occurred_at,
                provider="openai",
                model="text-embedding-3-small",
                purpose="embedding_kb_search",
                input_tokens=78,
                requests=5,
            ),
        ]
    )
    await db_session.flush()

    summary = await get_usage_summary(
        db_session,
        workspace_id=workspace.id,
        from_=datetime(2026, 8, 13, tzinfo=UTC),
        to=datetime(2026, 8, 14, tzinfo=UTC),
    )

    assert summary.totals.estimated_cost_usd == Decimal("0.054017")
    assert summary.totals.tokens_by_class.model_dump() == {
        "input": 819,
        "cache_read": 395_052,
        "cache_write": 126_020,
        "output": 12_051,
    }
    assert summary.pricing_coverage.priced_tokens == 533_942


@pytest.mark.asyncio
async def test_summary_adds_gpt_image_output_cost_and_exposes_incomplete_metadata(
    db_session: AsyncSession,
) -> None:
    workspace = build_workspace(slug=f"image-cost-{uuid4().hex}")
    db_session.add(workspace)
    await db_session.flush()
    occurred_at = datetime(2026, 8, 12, 12, tzinfo=UTC)
    db_session.add_all(
        [
            _event(
                workspace.id,
                occurred_at,
                purpose="image_generation",
                provider="openai",
                model="gpt-5.6-luna",
                input_tokens=1,
                details={
                    "action": "generate",
                    "image_model": "gpt-image-2",
                    "image_quality": "medium",
                    "image_size": "1024x1024",
                },
            ),
            _event(
                workspace.id,
                occurred_at,
                purpose="image_generation",
                provider="openai",
                model="gpt-5.6-luna",
                input_tokens=1,
                details={"action": "generate", "image_model": "gpt-image-2"},
            ),
        ]
    )
    await db_session.flush()

    summary = await get_usage_summary(
        db_session,
        workspace_id=workspace.id,
        from_=datetime(2026, 8, 12, tzinfo=UTC),
        to=datetime(2026, 8, 13, tzinfo=UTC),
    )

    assert summary.totals.estimated_cost_usd == Decimal("0.0530004")
    assert summary.pricing_coverage.priced_image_generations == 1
    assert summary.pricing_coverage.unpriced_image_generations == 1


@pytest.mark.asyncio
async def test_summary_adds_gemini_flash_image_output_cost(
    db_session: AsyncSession,
) -> None:
    workspace = build_workspace(slug=f"gemini-image-cost-{uuid4().hex}")
    db_session.add(workspace)
    await db_session.flush()
    occurred_at = datetime(2026, 8, 12, 12, tzinfo=UTC)
    db_session.add(
        _event(
            workspace.id,
            occurred_at,
            purpose="image_generation",
            provider="google",
            model="gemini-3.1-flash-image",
            details={
                "action": "generate",
                "image_model": "gemini-3.1-flash-image",
                "image_quality": "standard",
                "image_size": "1k",
            },
        )
    )
    await db_session.flush()

    summary = await get_usage_summary(
        db_session,
        workspace_id=workspace.id,
        from_=datetime(2026, 8, 12, tzinfo=UTC),
        to=datetime(2026, 8, 13, tzinfo=UTC),
    )

    assert summary.totals.estimated_cost_usd == Decimal("0.067")
    assert summary.pricing_coverage.priced_image_generations == 1
    assert summary.pricing_coverage.unpriced_image_generations == 0


@pytest.mark.asyncio
async def test_breakdown_labels_soft_deleted_and_unattributed_entities(
    db_session: AsyncSession,
) -> None:
    owner = build_user(email=f"usage-owner-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"labels-{uuid4().hex}")
    db_session.add_all([owner, workspace])
    await db_session.flush()
    agent = Agent(
        id=uuid4(),
        name="Former agent",
        slug=f"former-{uuid4().hex}",
        instructions="Test",
        workspace_id=workspace.id,
        created_by=owner.id,
        deleted=True,
    )
    removed_user = build_user(email=f"removed-{uuid4().hex}@example.com")
    removed_user.deleted = True
    db_session.add_all([agent, removed_user])
    await db_session.flush()
    occurred_at = datetime(2026, 8, 12, 12, tzinfo=UTC)
    db_session.add_all(
        [
            _event(workspace.id, occurred_at, agent_id=agent.id, user_id=removed_user.id),
            _event(workspace.id, occurred_at, agent_id=None, user_id=None),
        ]
    )
    await db_session.flush()

    agents = await get_usage_breakdown(
        db_session,
        workspace_id=workspace.id,
        dimension=UsageDimension.AGENT,
        from_=datetime(2026, 8, 12, tzinfo=UTC),
        to=datetime(2026, 8, 13, tzinfo=UTC),
    )
    users = await get_usage_breakdown(
        db_session,
        workspace_id=workspace.id,
        dimension=UsageDimension.USER,
        from_=datetime(2026, 8, 12, tzinfo=UTC),
        to=datetime(2026, 8, 13, tzinfo=UTC),
    )

    assert {row.label for row in agents.rows} == {"Removed agent", "Unattributed"}
    assert {row.label for row in users.rows} == {"Removed user", "Unattributed"}


@pytest.mark.parametrize(
    ("from_", "to"),
    [
        (
            datetime(2026, 1, 2, tzinfo=UTC),
            datetime(2026, 1, 1, tzinfo=UTC),
        ),
        (
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 4, 4, tzinfo=UTC),
        ),
        (
            datetime(2026, 1, 1),  # noqa: DTZ001 - deliberately naive
            datetime(2026, 1, 2),  # noqa: DTZ001 - deliberately naive
        ),
    ],
)
def test_range_validation_rejects_invalid_ranges(from_: datetime, to: datetime) -> None:
    with pytest.raises(AppValidationError):
        resolve_usage_range(from_, to)
