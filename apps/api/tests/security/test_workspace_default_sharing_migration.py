"""Verifies the workspace audience migration against PostgreSQL."""

from pathlib import Path
from runpy import run_path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tests.support.database import make_async_test_database_url


@pytest.mark.asyncio
async def test_workspace_default_sharing_migration_round_trip(test_database_url):
    engine = create_async_engine(
        make_async_test_database_url(test_database_url), poolclass=NullPool
    )
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.run_sync(_verify_migration)
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


def _verify_migration(connection):
    schema = f"workspace_sharing_migration_{uuid4().hex}"
    connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
    connection.exec_driver_sql("CREATE TABLE workspaces (id integer PRIMARY KEY)")
    connection.exec_driver_sql("INSERT INTO workspaces (id) VALUES (1)")
    migration = run_path(
        str(
            Path(__file__).resolve().parents[2]
            / "alembic/versions/core/0058_add_workspace_default_sharing.py"
        )
    )
    migration["upgrade"].__globals__["op"] = Operations(MigrationContext.configure(connection))
    migration["upgrade"]()
    column = next(
        column
        for column in inspect(connection).get_columns("workspaces", schema=schema)
        if column["name"] == "conversations_shared_by_default"
    )
    assert column["nullable"] is False
    assert column["default"] == "false"
    connection.exec_driver_sql("INSERT INTO workspaces (id) VALUES (2)")
    assert connection.exec_driver_sql(
        "SELECT conversations_shared_by_default FROM workspaces ORDER BY id"
    ).scalars().all() == [False, False]
    with pytest.raises(IntegrityError), connection.begin_nested():
        connection.exec_driver_sql("UPDATE workspaces SET conversations_shared_by_default = NULL")
    connection.exec_driver_sql("UPDATE workspaces SET conversations_shared_by_default = true")
    migration["downgrade"]()
    assert [column["name"] for column in inspect(connection).get_columns("workspaces")] == ["id"]
    assert connection.exec_driver_sql("SELECT id FROM workspaces ORDER BY id").scalars().all() == [
        1,
        2,
    ]
