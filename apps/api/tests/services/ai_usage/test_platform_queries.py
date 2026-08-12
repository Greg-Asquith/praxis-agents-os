"""Cross-workspace AI usage aggregation and read-only boundary tests."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import delete, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.database import (
    configure_async_db_session,
    get_maintenance_async_db_session_factory,
)
from models.ai_usage_event import AIUsageEvent
from models.workspace import Workspace
from services.ai_usage.get_usage_summary import get_usage_summary
from services.ai_usage.platform_queries import (
    get_platform_usage_breakdown,
    get_platform_usage_summary,
)
from services.ai_usage.schemas import PlatformUsageDimension
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


async def test_platform_queries_reconcile_across_workspaces_and_are_read_only(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    shared_user = build_user(
        email=f"platform-shared-{uuid4().hex}@example.com",
        display_name="Shared Operator",
    )
    removed_user = build_user(email=f"platform-removed-{uuid4().hex}@example.com")
    removed_user.deleted = True
    workspace_a = build_workspace(
        slug=f"platform-a-{uuid4().hex[:8]}",
        name="Platform A",
    )
    workspace_b = build_workspace(
        slug=f"platform-b-{uuid4().hex[:8]}",
        name="Platform B",
    )
    workspace_b.deleted = True
    async with get_maintenance_async_db_session_factory()() as seed_db:
        seed_db.add_all([shared_user, removed_user, workspace_a, workspace_b])
        await seed_db.flush()
        seed_db.add_all(
            [
                _event(
                    workspace_a.id,
                    datetime(2026, 8, 31, 23, 59, tzinfo=UTC),
                    user_id=shared_user.id,
                    requests=3,
                ),
                _event(
                    workspace_b.id,
                    datetime(2026, 9, 1, 0, 0, tzinfo=UTC),
                    user_id=shared_user.id,
                    requests=2,
                ),
                _event(
                    workspace_b.id,
                    datetime(2026, 9, 1, 1, 0, tzinfo=UTC),
                    provider="azure",
                    model="customer-deployment",
                    input_tokens=2,
                    user_id=None,
                    requests=7,
                ),
                _event(
                    workspace_a.id,
                    datetime(2026, 9, 1, 2, 0, tzinfo=UTC),
                    input_tokens=0,
                    user_id=removed_user.id,
                    requests=0,
                ),
            ]
        )
        await seed_db.commit()

    usage_range = {
        "from_": datetime(2026, 8, 31, tzinfo=UTC),
        "to": datetime(2026, 9, 2, tzinfo=UTC),
    }
    async with get_maintenance_async_db_session_factory()() as query_db:
        await configure_async_db_session(query_db)
        summary = await get_platform_usage_summary(query_db, **usage_range)

        assert summary.totals.estimated_cost_usd == Decimal("5")
        assert summary.totals.requests == 12
        assert summary.pricing_coverage.priced_tokens == 2_000_000
        assert summary.pricing_coverage.unpriced_tokens == 2
        assert summary.pricing_coverage.priced_requests == 5
        assert summary.pricing_coverage.unpriced_requests == 7
        assert [point.estimated_cost_usd for point in summary.daily] == [
            Decimal("2"),
            Decimal("3"),
        ]

        query_db.add(build_workspace(slug=f"read-only-{uuid4().hex[:8]}"))
        with pytest.raises(DBAPIError, match="read-only transaction"):
            await query_db.flush()
        await query_db.rollback()

    async with get_maintenance_async_db_session_factory()() as reconcile_db:
        workspace_summaries = [
            await get_usage_summary(reconcile_db, workspace_id=workspace.id, **usage_range)
            for workspace in (workspace_a, workspace_b)
        ]
    assert summary.totals.requests == sum(item.totals.requests for item in workspace_summaries)
    assert summary.totals.estimated_cost_usd == sum(
        (item.totals.estimated_cost_usd for item in workspace_summaries),
        start=Decimal(0),
    )

    async with get_maintenance_async_db_session_factory()() as user_db:
        users = await get_platform_usage_breakdown(
            user_db,
            dimension=PlatformUsageDimension.USER,
            **usage_range,
        )
    shared_row = next(row for row in users.rows if row.key == str(shared_user.id))
    unattributed_row = next(row for row in users.rows if row.key == "unattributed")
    removed_row = next(row for row in users.rows if row.key == str(removed_user.id))
    assert shared_row.label == f"Shared Operator · {shared_user.email}"
    assert shared_row.requests == 5
    assert sum(shared_row.tokens_by_class.model_dump().values()) == 2_000_000
    assert unattributed_row.requests == 7
    assert unattributed_row.estimated_cost_usd is None
    assert removed_row.label == "Removed user"

    async with get_maintenance_async_db_session_factory()() as dimensions_db:
        purposes = await get_platform_usage_breakdown(
            dimensions_db,
            dimension=PlatformUsageDimension.PURPOSE,
            **usage_range,
        )
        models = await get_platform_usage_breakdown(
            dimensions_db,
            dimension=PlatformUsageDimension.MODEL,
            **usage_range,
        )
    assert sum(row.requests for row in purposes.rows) == summary.totals.requests
    assert {row.key for row in models.rows} == {
        "anthropic:claude-sonnet-5",
        "azure:customer-deployment",
    }

    async with get_maintenance_async_db_session_factory()() as workspace_db:
        workspaces = await get_platform_usage_breakdown(
            workspace_db,
            dimension=PlatformUsageDimension.WORKSPACE,
            **usage_range,
        )
    assert {row.label for row in workspaces.rows} == {
        f"Platform A · {workspace_a.slug}",
        "Removed workspace",
    }

    async with get_maintenance_async_db_session_factory()() as cleanup_db:
        await cleanup_db.execute(
            delete(Workspace).where(Workspace.id.in_([workspace_a.id, workspace_b.id]))
        )
        await cleanup_db.commit()


def _plan_nodes(node: dict[str, Any]):
    yield node
    for child in node.get("Plans", []):
        yield from _plan_nodes(child)


async def test_platform_time_range_query_uses_global_occurred_index(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    del committed_db_session_factory
    workspaces = [
        build_workspace(slug=f"platform-index-{index}-{uuid4().hex[:8]}") for index in range(4)
    ]
    async with get_maintenance_async_db_session_factory()() as seed_db:
        seed_db.add_all(workspaces)
        await seed_db.flush()
        for workspace in workspaces:
            await seed_db.execute(
                text(
                    """
                    INSERT INTO ai_usage_events (
                        id, workspace_id, occurred_at, provider, model, purpose,
                        input_tokens, cache_read_tokens, cache_write_tokens,
                        output_tokens, requests
                    )
                    SELECT
                        gen_random_uuid(), :workspace_id,
                        TIMESTAMPTZ '2026-01-01 00:00:00+00'
                            + (series % 180) * INTERVAL '1 day',
                        'openai', 'gpt-5.6-luna', 'agent_run', 10, 0, 0, 2, 1
                    FROM generate_series(1, 5000) AS series
                    """
                ),
                {"workspace_id": workspace.id},
            )
        await seed_db.commit()

    try:
        async with get_maintenance_async_db_session_factory()() as query_db:
            await query_db.execute(text("ANALYZE ai_usage_events"))
            explain = await query_db.execute(
                text(
                    """
                    EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
                    SELECT
                        date_trunc('day', timezone('UTC', occurred_at)),
                        provider,
                        model,
                        SUM(requests)
                    FROM ai_usage_events
                    WHERE occurred_at >= TIMESTAMPTZ '2026-03-01 00:00:00+00'
                      AND occurred_at < TIMESTAMPTZ '2026-03-02 00:00:00+00'
                    GROUP BY 1, 2, 3
                    """
                )
            )
            [document] = explain.scalar_one()
            indexes = {
                str(node["Index Name"])
                for node in _plan_nodes(document["Plan"])
                if node.get("Index Name") is not None
            }
            print(  # noqa: T201 - retained query-plan completion evidence
                json.dumps(
                    {
                        "execution_time_ms": float(document["Execution Time"]),
                        "indexes": sorted(indexes),
                        "seeded_rows": 20_000,
                        "workspaces": len(workspaces),
                    },
                    sort_keys=True,
                )
            )
            assert "ix_ai_usage_events_occurred_at" in indexes
    finally:
        async with get_maintenance_async_db_session_factory()() as cleanup_db:
            await cleanup_db.execute(
                delete(Workspace).where(Workspace.id.in_([item.id for item in workspaces]))
            )
            await cleanup_db.commit()
