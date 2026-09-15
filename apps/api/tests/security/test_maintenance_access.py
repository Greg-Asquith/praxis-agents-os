"""Verifies maintenance access without superuser privileges or an RLS bypass."""

from datetime import UTC, datetime
from pathlib import Path
from runpy import run_path
from uuid import UUID, uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.database import get_maintenance_async_db_session_factory, set_session_tenant_context
from models.ai_usage_event import AIUsageEvent
from services.ai_usage.platform_queries import (
    get_platform_usage_breakdown,
    get_platform_usage_summary,
)
from services.ai_usage.schemas import PlatformUsageDimension
from tests.factories import build_workspace


def _migrate(connection, direction: str) -> None:
    migration = run_path(
        str(
            Path(__file__).resolve().parents[2]
            / "alembic/versions/core/0056_add_maintenance_access_policies.py"
        )
    )
    migration[direction].__globals__["op"] = Operations(MigrationContext.configure(connection))
    migration[direction]()


def _event(workspace_id: UUID | None) -> AIUsageEvent:
    return AIUsageEvent(
        id=uuid4(),
        scope="platform" if workspace_id is None else "workspace",
        workspace_id=workspace_id,
        occurred_at=datetime(2198, 1, 1, 12, tzinfo=UTC),
        provider="openai",
        model="test-model",
        purpose="kb_annotation",
        input_tokens=123,
        requests=1,
    )


async def test_maintenance_policy_restores_usage_without_widening_runtime_access(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    role = "maintenance_test_" + uuid4().hex
    async with get_maintenance_async_db_session_factory()() as db:
        try:
            workspaces = [build_workspace(slug=f"maintenance-{uuid4().hex}") for _ in range(2)]
            db.add_all(workspaces)
            await db.flush()
            events = [_event(workspace.id) for workspace in workspaces]
            db.add_all(events)
            await db.flush()
            connection = await db.connection()
            await connection.run_sync(lambda sync: _migrate(sync, "downgrade"))
            await db.execute(text(f"CREATE ROLE {role} NOLOGIN NOSUPERUSER NOBYPASSRLS"))
            await db.execute(text(f"GRANT USAGE, CREATE ON SCHEMA public TO {role}"))
            await db.execute(text(f"GRANT SELECT ON workspaces, users TO {role}"))
            tables = await db.scalars(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND rowsecurity")
            )
            for table in tables:
                quoted = connection.dialect.identifier_preparer.quote(table)
                await db.execute(text(f"ALTER TABLE public.{quoted} OWNER TO {role}"))
            await db.execute(text(f"SET LOCAL ROLE {role}"))
            count = select(func.count()).select_from(AIUsageEvent)
            assert await db.scalar(count) == 0

            # The table owner installs its policy without elevated role attributes.
            await connection.run_sync(lambda sync: _migrate(sync, "upgrade"))
            platform_event = _event(None)
            db.add(platform_event)
            await db.flush()
            event_ids = [event.id for event in events] + [platform_event.id]
            assert await db.scalar(count.where(AIUsageEvent.id.in_(event_ids))) == 3

            await db.execute(text("SET LOCAL ROLE praxis_app"))
            await set_session_tenant_context(db, workspace_id=workspaces[0].id)
            assert list(
                await db.scalars(select(AIUsageEvent.id).where(AIUsageEvent.id.in_(event_ids)))
            ) == [events[0].id]
            with pytest.raises(DBAPIError, match="row-level security"):
                async with connection.begin_nested():
                    await db.execute(
                        AIUsageEvent.__table__.insert().values(
                            scope="platform",
                            provider="openai",
                            model="test-model",
                            purpose="kb_annotation",
                        )
                    )

            await db.execute(text(f"SET LOCAL ROLE {role}"))
            usage_range = {
                "from_": datetime(2198, 1, 1, tzinfo=UTC),
                "to": datetime(2198, 1, 2, tzinfo=UTC),
            }
            summary = await get_platform_usage_summary(db, **usage_range)
            breakdown = await get_platform_usage_breakdown(
                db, dimension=PlatformUsageDimension.WORKSPACE, **usage_range
            )
            assert summary.totals.requests == 3
            assert len(breakdown.rows) == 3
        finally:
            await db.rollback()
