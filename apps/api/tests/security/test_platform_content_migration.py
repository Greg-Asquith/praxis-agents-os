"""Check populated platform-content migration upgrades and guarded downgrades."""

from pathlib import Path
from runpy import run_path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from core.database import get_maintenance_async_db_session_factory
from tests.security.test_workspace_rls import (
    PLATFORM_FAMILIES,
    PLATFORM_TABLES,
    _insert_seed,
    _reflect_table,
    _seed_resource_family,
)


@pytest.fixture(autouse=True)
async def clean_platform_content(db_session_factory):
    # Releasing this savepoint retains cleanup only inside the fixture's outer rollback.
    async with get_maintenance_async_db_session_factory()() as db:
        await db.execute(sa.text("SET LOCAL session_replication_role = replica"))
        for table_name in (*PLATFORM_TABLES, "file_uploads"):
            table = await _reflect_table(db, table_name)
            await db.execute(sa.delete(table).where(table.c.scope == "platform"))
        await db.execute(sa.text("SET LOCAL session_replication_role = origin"))
        await db.commit()


def _run_migration(connection, direction):
    migration = run_path(
        str(
            Path(__file__).resolve().parents[2]
            / "alembic/versions/core/0054_add_platform_content.py"
        )
    )
    migration[direction].__globals__["op"] = Operations(MigrationContext.configure(connection))
    migration[direction]()


async def test_platform_content_migration_preserves_populated_workspace_rows(db_session_factory):
    # The shared fixture rolls back DDL and data together under its database lock.
    async with get_maintenance_async_db_session_factory()() as db:
        connection = await db.connection()
        await connection.run_sync(lambda sync: _run_migration(sync, "downgrade"))
        workspace_id = uuid4()
        workspaces = await _reflect_table(db, "workspaces")
        await _insert_seed(
            db,
            workspaces,
            workspace_id=workspace_id,
            marker="owner",
            overrides={"id": workspace_id},
        )
        expected = {}
        for family in PLATFORM_FAMILIES:
            parent = await _reflect_table(db, family[0])
            child = await _reflect_table(db, family[1])
            parent_id = (
                await _insert_seed(db, parent, workspace_id=workspace_id, marker="legacy")
            )[0]
            child_id = (
                await _insert_seed(
                    db,
                    child,
                    workspace_id=workspace_id,
                    marker="legacy",
                    overrides={family[2]: parent_id},
                )
            )[0]
            if family[3]:
                await db.execute(
                    sa.update(parent)
                    .where(parent.c.id == parent_id)
                    .values(**{family[3]: child_id})
                )
            expected[parent.name] = parent_id
            expected[child.name] = child_id
        uploads = await _reflect_table(db, "file_uploads")
        await db.execute(sa.text("SET LOCAL session_replication_role = replica"))
        expected[uploads.name] = (
            await _insert_seed(db, uploads, workspace_id=workspace_id, marker="legacy")
        )[0]
        await db.execute(sa.text("SET LOCAL session_replication_role = origin"))
        await connection.run_sync(lambda sync: _run_migration(sync, "upgrade"))
        for table_name, row_id in expected.items():
            table = await _reflect_table(db, table_name)
            row = (await db.execute(sa.select(table).where(table.c.id == row_id))).one()._mapping
            assert row["scope"] == "workspace"
            assert row["workspace_id"] == workspace_id
            if table_name in PLATFORM_TABLES:
                assert row["is_published"] is False
        for family in PLATFORM_FAMILIES[1:]:
            parent = await _reflect_table(db, family[0])
            row = (
                (await db.execute(sa.select(parent).where(parent.c.id == expected[parent.name])))
                .one()
                ._mapping
            )
            assert row[family[3]] == expected[family[1]]
            assert row[family[4]] is None
        await connection.run_sync(lambda sync: _run_migration(sync, "downgrade"))
        for table_name, row_id in expected.items():
            table = await _reflect_table(db, table_name)
            assert "scope" not in table.c
            assert (
                await db.scalar(sa.select(table.c.workspace_id).where(table.c.id == row_id))
                == workspace_id
            )
        await connection.run_sync(lambda sync: _run_migration(sync, "upgrade"))


@pytest.mark.parametrize("family", PLATFORM_FAMILIES, ids=lambda family: family[0])
async def test_platform_content_migration_refuses_downgrade_with_platform_rows(
    family, db_session_factory
):
    async with get_maintenance_async_db_session_factory()() as db:
        parent, child, parent_id, child_ids = await _seed_resource_family(
            db, family, workspace_id=uuid4()
        )
        connection = await db.connection()
        with pytest.raises((RuntimeError, sa.exc.DBAPIError), match=r"[Pp]latform"):
            async with connection.begin_nested():
                await connection.run_sync(lambda sync: _run_migration(sync, "downgrade"))
        assert await db.scalar(sa.select(parent.c.id).where(parent.c.id == parent_id)) == parent_id
        assert set(
            (await db.scalars(sa.select(child.c.id).where(child.c.id.in_(child_ids)))).all()
        ) == set(child_ids)


@pytest.mark.parametrize(
    "table_name", ("file_uploads", "kb_chunks", "file_revisions", "artifact_revisions")
)
async def test_platform_content_migration_refuses_downgrade_for_each_child_or_grant(
    table_name, db_session_factory
):
    async with get_maintenance_async_db_session_factory()() as db:
        table = await _reflect_table(db, table_name)
        # Isolate each guard, including orphan rows retained after an interrupted repair.
        await db.execute(sa.text("SET LOCAL session_replication_role = replica"))
        row_id = (
            await _insert_seed(
                db,
                table,
                workspace_id=uuid4(),
                marker="platform",
                overrides={"scope": "platform", "workspace_id": None},
            )
        )[0]
        await db.execute(sa.text("SET LOCAL session_replication_role = origin"))
        connection = await db.connection()
        with pytest.raises(sa.exc.DBAPIError, match="Export and remove platform content"):
            async with connection.begin_nested():
                await connection.run_sync(lambda sync: _run_migration(sync, "downgrade"))
        assert await db.scalar(sa.select(table.c.id).where(table.c.id == row_id)) == row_id


@pytest.mark.parametrize("family", PLATFORM_FAMILIES, ids=lambda family: family[0])
async def test_platform_content_migration_rejects_legacy_owner_mismatch_before_schema_changes(
    family, db_session_factory
):
    async with get_maintenance_async_db_session_factory()() as db:
        connection = await db.connection()
        await connection.run_sync(lambda sync: _run_migration(sync, "downgrade"))
        parent_owner, child_owner = uuid4(), uuid4()
        workspaces = await _reflect_table(db, "workspaces")
        for owner in (parent_owner, child_owner):
            await _insert_seed(
                db, workspaces, workspace_id=owner, marker="owner", overrides={"id": owner}
            )
        parent = await _reflect_table(db, family[0])
        child = await _reflect_table(db, family[1])
        parent_id = (await _insert_seed(db, parent, workspace_id=parent_owner, marker="legacy"))[0]
        child_id = (
            await _insert_seed(
                db,
                child,
                workspace_id=child_owner,
                marker="legacy",
                overrides={family[2]: parent_id},
            )
        )[0]
        with pytest.raises(sa.exc.DBAPIError, match="Repair inconsistent content ownership"):
            async with connection.begin_nested():
                await connection.run_sync(lambda sync: _run_migration(sync, "upgrade"))
        for table_name in (*PLATFORM_TABLES, "file_uploads"):
            assert "scope" not in (await _reflect_table(db, table_name)).c
        assert (
            await db.scalar(sa.select(child.c.workspace_id).where(child.c.id == child_id))
            == child_owner
        )
        assert (
            await db.scalar(sa.select(parent.c.workspace_id).where(parent.c.id == parent_id))
            == parent_owner
        )
