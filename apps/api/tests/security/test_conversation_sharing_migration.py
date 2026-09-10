"""Qualify sharing migration transitions without modifying application schemas."""

from pathlib import Path
from runpy import run_path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from tests.support.database import make_async_test_database_url


@pytest.mark.asyncio
async def test_sharing_migration_backfills_and_round_trips(test_database_url):
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
    # The schema and every migration change roll back together, including on failure.
    schema = f"sharing_migration_{uuid4().hex}"
    connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
    connection.exec_driver_sql("CREATE TABLE users (id uuid PRIMARY KEY)")
    connection.exec_driver_sql(
        "CREATE TABLE conversations (id uuid PRIMARY KEY, workspace_id uuid NOT NULL, "
        "source varchar(32) NOT NULL, deleted boolean NOT NULL DEFAULT false, "
        "created_at timestamptz NOT NULL DEFAULT now(), last_message_at timestamptz)"
    )
    connection.exec_driver_sql("ALTER TABLE conversations ENABLE ROW LEVEL SECURITY")
    connection.exec_driver_sql("ALTER TABLE conversations FORCE ROW LEVEL SECURITY")
    connection.exec_driver_sql(
        "CREATE POLICY conversations_workspace_policy ON conversations "
        "USING (workspace_id = nullif(current_setting('app.current_workspace_id', true), '')::uuid)"
    )
    workspace_id = uuid4()
    connection.execute(
        text("SELECT set_config('app.current_workspace_id', :workspace, true)"),
        {"workspace": str(workspace_id)},
    )
    for source in ("direct", "scheduled", "event", "delegated"):
        connection.execute(
            text(
                "INSERT INTO conversations (id, workspace_id, source) VALUES (:id, :workspace, :source)"
            ),
            {"id": uuid4(), "workspace": workspace_id, "source": source},
        )
    migration = run_path(
        str(
            Path(__file__).resolve().parents[2]
            / "alembic/versions/core/0053_add_conversation_sharing.py"
        )
    )
    migration["upgrade"].__globals__["op"] = Operations(MigrationContext.configure(connection))
    migration["upgrade"]()
    _assert_upgraded(connection, schema)
    for statement in (
        "UPDATE conversations SET visibility = 'public' WHERE source = 'direct'",
        "UPDATE conversations SET visibility = 'workspace' WHERE source = 'delegated'",
        "UPDATE conversations SET shared_by_user_id = gen_random_uuid() WHERE source = 'direct'",
    ):
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.exec_driver_sql(statement)
    connection.exec_driver_sql(
        "UPDATE conversations SET visibility = 'workspace' WHERE source = 'direct'"
    )
    migration["downgrade"]()
    inspector = inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("conversations", schema=schema)}
    assert not columns.intersection({"visibility", "shared_at", "shared_by_user_id"})
    assert not inspector.get_indexes("conversations", schema=schema)
    assert not inspector.get_check_constraints("conversations", schema=schema)
    assert not inspector.get_foreign_keys("conversations", schema=schema)
    assert connection.exec_driver_sql("SELECT count(*) FROM conversations").scalar_one() == 4
    migration["upgrade"]()
    _assert_upgraded(connection, schema)


def _assert_upgraded(connection, schema):
    rows = connection.exec_driver_sql(
        "SELECT source, visibility, shared_at, shared_by_user_id FROM conversations ORDER BY source"
    ).all()
    assert rows == [
        (source, "private", None, None) for source in ("delegated", "direct", "event", "scheduled")
    ]
    inspector = inspect(connection)
    visibility = next(
        column
        for column in inspector.get_columns("conversations", schema=schema)
        if column["name"] == "visibility"
    )
    assert visibility["nullable"] is False
    assert "private" in visibility["default"]
    indexes = inspector.get_indexes("conversations", schema=schema)
    assert len(indexes) == 1
    assert indexes[0]["name"] == "ix_conversations_workspace_shared"
    definition = connection.execute(
        text(
            "SELECT indexdef FROM pg_indexes WHERE schemaname = :schema AND indexname = 'ix_conversations_workspace_shared'"
        ),
        {"schema": schema},
    ).scalar_one()
    for fragment in (
        "workspace_id",
        "COALESCE(last_message_at, created_at) DESC",
        "created_at DESC",
        "id DESC",
        "visibility",
        "workspace",
        "deleted",
        "delegated",
    ):
        assert fragment in definition
    rls = connection.execute(
        text(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class JOIN pg_namespace ON pg_namespace.oid = pg_class.relnamespace WHERE nspname = :schema AND relname = 'conversations'"
        ),
        {"schema": schema},
    ).one()
    assert tuple(rls) == (True, True)
    assert (
        connection.execute(
            text(
                "SELECT count(*) FROM pg_policies WHERE schemaname = :schema AND tablename = 'conversations' AND policyname = 'conversations_workspace_policy'"
            ),
            {"schema": schema},
        ).scalar_one()
        == 1
    )
