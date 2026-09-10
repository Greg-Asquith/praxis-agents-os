"""Verifies usage ownership backfill and accounting-preserving downgrades."""

from datetime import date
from pathlib import Path
from runpy import run_path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from core.database import get_maintenance_async_db_session_factory
from tests.security.test_workspace_rls import _insert_seed, _reflect_table

_USAGE_TABLES = ("ai_usage_events", "embedding_token_usage")


@pytest.fixture(autouse=True)
async def clean_platform_usage(db_session_factory):
    # The shared fixture rolls back these removals and all migration DDL together.
    async with get_maintenance_async_db_session_factory()() as db:
        for table_name in _USAGE_TABLES:
            table = await _reflect_table(db, table_name)
            await db.execute(sa.delete(table).where(table.c.scope == "platform"))
        table = await _reflect_table(db, "platform_ingestion_usage")
        await db.execute(sa.delete(table))
        await db.commit()


def _run_migration(connection, direction):
    migration = run_path(
        str(
            Path(__file__).resolve().parents[2]
            / "alembic/versions/core/0055_add_platform_usage_ownership.py"
        )
    )
    migration[direction].__globals__["op"] = Operations(MigrationContext.configure(connection))
    migration[direction]()


async def test_platform_usage_migration_preserves_populated_workspace_rows(db_session_factory):
    async with get_maintenance_async_db_session_factory()() as db:
        connection = await db.connection()
        await connection.run_sync(lambda sync: _run_migration(sync, "downgrade"))
        workspace_id = uuid4()
        workspaces = await _reflect_table(db, "workspaces")
        await _insert_seed(
            db,
            workspaces,
            workspace_id=workspace_id,
            marker="usage-owner",
            overrides={"id": workspace_id},
        )
        expected = {}
        for table_name in _USAGE_TABLES:
            table = await _reflect_table(db, table_name)
            expected[table_name] = (
                await _insert_seed(db, table, workspace_id=workspace_id, marker="legacy-usage")
            )[0]
        await connection.run_sync(lambda sync: _run_migration(sync, "upgrade"))
        for table_name, row_id in expected.items():
            table = await _reflect_table(db, table_name)
            row = (await db.execute(sa.select(table).where(table.c.id == row_id))).one()._mapping
            assert row["workspace_id"] == workspace_id
            assert row["scope"] == "workspace"
        await connection.run_sync(lambda sync: _run_migration(sync, "downgrade"))
        for table_name, row_id in expected.items():
            table = await _reflect_table(db, table_name)
            assert "scope" not in table.c
            assert (
                await db.scalar(sa.select(table.c.workspace_id).where(table.c.id == row_id))
                == workspace_id
            )
        await connection.run_sync(lambda sync: _run_migration(sync, "upgrade"))


@pytest.mark.parametrize("table_name", (*_USAGE_TABLES, "platform_ingestion_usage"))
async def test_platform_usage_migration_refuses_to_discard_accounting(
    table_name, db_session_factory
):
    async with get_maintenance_async_db_session_factory()() as db:
        table = await _reflect_table(db, table_name)
        overrides = (
            {"scope": "platform", "workspace_id": None}
            if table_name in _USAGE_TABLES
            else {"period_month": date(2026, 9, 1), "requests_reserved": 3}
        )
        if table_name == "ai_usage_events":
            overrides["purpose"] = "embedding_kb_ingest"
        row_id = (
            await _insert_seed(
                db, table, workspace_id=uuid4(), marker="platform-accounting", overrides=overrides
            )
        )[0]
        connection = await db.connection()
        with pytest.raises(sa.exc.DBAPIError, match="Remove platform accounting"):
            async with connection.begin_nested():
                await connection.run_sync(lambda sync: _run_migration(sync, "downgrade"))
        assert await db.scalar(sa.select(table.c.id).where(table.c.id == row_id)) == row_id
        for usage_table in _USAGE_TABLES:
            assert "scope" in (await _reflect_table(db, usage_table)).c
