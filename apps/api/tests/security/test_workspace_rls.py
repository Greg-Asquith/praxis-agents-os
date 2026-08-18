"""Database-level workspace isolation invariants for every protected table."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.database import (
    get_maintenance_async_db_session_factory,
    set_session_tenant_context,
)

pytestmark = pytest.mark.asyncio

DIRECT_TABLES = (
    "agents",
    "agent_schedules",
    "agent_schedule_runs",
    "agent_runs",
    "agent_memories",
    "conversations",
    "conversation_todos",
    "conversation_messages",
    "conversation_summaries",
    "artifacts",
    "artifact_revisions",
    "artifact_shares",
    "files",
    "file_folders",
    "file_revisions",
    "file_references",
    "file_uploads",
    "kb_documents",
    "kb_chunks",
    "skills",
    "classifiers",
    "embedding_token_usage",
    "scratch_entries",
    "workspace_tool_settings",
    "integration_context_groups",
    "active_context_selections",
    "audit_events",
    "ai_usage_events",
)
DUAL_OWNER_TABLES = (
    "external_credentials",
    "integration_connections",
    "notifications",
)
INDIRECT_TABLES = (
    "integration_oauth_states",
    "integration_resources",
    "integration_discovery_runs",
    "integration_webhooks",
    "integration_events",
    "integration_table_schemas",
    "integration_context_group_members",
)
RLS_TABLES = (*DIRECT_TABLES, *DUAL_OWNER_TABLES, *INDIRECT_TABLES)


async def _reflect_table(db: AsyncSession, table_name: str) -> sa.Table:
    connection = await db.connection()
    return await connection.run_sync(
        lambda sync_connection: sa.Table(
            table_name,
            sa.MetaData(),
            autoload_with=sync_connection,
        )
    )


def _required_value(
    table_name: str,
    column: sa.Column,
    *,
    workspace_id: UUID,
    marker: str,
) -> object:
    name = column.name
    column_type = column.type
    table_values: dict[tuple[str, str], object] = {
        ("agent_memories", "scope"): "workspace",
        ("agent_memories", "source"): "interactive",
        ("agent_memories", "created_by"): "user",
        ("agent_runs", "trigger"): "interactive",
        ("agent_schedules", "schedule_type"): "once",
        ("artifact_revisions", "revision_kind"): "create",
        ("artifacts", "artifact_type"): "markdown",
        ("conversation_messages", "role"): "user",
        ("external_credentials", "auth_mode"): "api_key",
        ("file_revisions", "revision_kind"): "create",
        ("file_references", "target_type"): "conversation",
        ("integration_events", "payload_digest"): marker * 64,
        ("integration_table_schemas", "table_type"): "table",
        ("kb_documents", "source_type"): "manual",
        ("ai_usage_events", "provider"): "openai",
        ("ai_usage_events", "model"): "gpt-5.6-luna",
        ("ai_usage_events", "purpose"): "agent_run",
    }
    if (table_name, name) in table_values:
        return table_values[(table_name, name)]
    if name in {"workspace_id", "owner_workspace_id"}:
        return workspace_id
    if name == "owner_user_id":
        return None
    if isinstance(column_type, postgresql.UUID):
        return uuid4()
    if isinstance(column_type, (sa.String, sa.Text)):
        value = f"rls-{marker}-{name}-{uuid4().hex[:8]}"
        return value[: column_type.length] if column_type.length else value
    if isinstance(column_type, sa.Boolean):
        return False
    if isinstance(column_type, (sa.Integer, sa.BigInteger)):
        return 1
    if isinstance(column_type, sa.DateTime):
        return datetime.now(UTC) + timedelta(days=1)
    if isinstance(column_type, sa.Date):
        return date(2026, 8, 1)
    if isinstance(column_type, (postgresql.JSONB, sa.JSON)):
        return [] if name == "parts" else {}
    if isinstance(column_type, postgresql.ARRAY):
        return []
    if isinstance(column_type, sa.LargeBinary):
        return b"rls"
    raise AssertionError(f"No RLS seed value for {table_name}.{name} ({column_type!r})")


def _seed_values(
    table: sa.Table,
    *,
    workspace_id: UUID,
    marker: str,
    overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    values: dict[str, object] = {}
    overrides = overrides or {}
    for column in table.columns:
        if column.name in overrides:
            values[column.name] = overrides[column.name]
        elif column.name in {"workspace_id", "owner_workspace_id"}:
            values[column.name] = workspace_id
        elif column.name == "owner_user_id":
            continue
        elif not column.nullable and column.server_default is None:
            values[column.name] = _required_value(
                table.name,
                column,
                workspace_id=workspace_id,
                marker=marker,
            )

    if table.name in {"artifact_revisions", "file_revisions"}:
        values["created_by_system"] = True
    if table.name == "file_folders":
        values["created_by_user_id"] = uuid4()
    if table.name == "scratch_entries":
        values["conversation_id"] = uuid4()
    if table.name == "active_context_selections":
        values["integration_resource_id"] = uuid4()
    if table.name == "kb_chunks":
        values.update(char_start=0, char_end=1)
    if table.name == "classifiers":
        values["labels"] = [
            {"label": "one", "description": None},
            {"label": "two", "description": None},
        ]
    if table.name == "external_credentials":
        values.update(
            secret_provider="test",  # noqa: S106 - non-secret fixture metadata
            secret_name=f"rls-{marker}-{uuid4().hex}",
            secret_version="latest",  # noqa: S106 - non-secret fixture metadata
        )
    return values


async def _insert_seed(
    db: AsyncSession,
    table: sa.Table,
    *,
    workspace_id: UUID,
    marker: str,
    overrides: dict[str, object] | None = None,
) -> tuple[object, ...]:
    values = _seed_values(
        table,
        workspace_id=workspace_id,
        marker=marker,
        overrides=overrides,
    )
    primary_keys = tuple(table.primary_key.columns)
    result = await db.execute(sa.insert(table).values(**values).returning(*primary_keys))
    return tuple(result.one())


async def _seed_integration_parents(
    db: AsyncSession,
    *,
    workspace_id: UUID,
    marker: str,
) -> tuple[UUID, UUID]:
    credential_table = await _reflect_table(db, "external_credentials")
    credential_pk = await _insert_seed(
        db,
        credential_table,
        workspace_id=workspace_id,
        marker=marker,
    )
    connection_table = await _reflect_table(db, "integration_connections")
    connection_pk = await _insert_seed(
        db,
        connection_table,
        workspace_id=workspace_id,
        marker=marker,
        overrides={"credential_id": credential_pk[0]},
    )
    return credential_pk[0], connection_pk[0]


async def _seed_protected_row(
    db: AsyncSession,
    table: sa.Table,
    *,
    workspace_id: UUID,
    marker: str,
) -> tuple[object, ...]:
    overrides: dict[str, object] = {}
    if table.name in INDIRECT_TABLES:
        _credential_id, connection_id = await _seed_integration_parents(
            db,
            workspace_id=workspace_id,
            marker=marker,
        )
        if "connection_id" in table.columns:
            overrides["connection_id"] = connection_id
        if table.name == "integration_table_schemas":
            resource_table = await _reflect_table(db, "integration_resources")
            resource_id = await _insert_seed(
                db,
                resource_table,
                workspace_id=workspace_id,
                marker=marker,
                overrides={"connection_id": connection_id},
            )
            overrides["resource_id"] = resource_id[0]
        if table.name == "integration_context_group_members":
            resource_table = await _reflect_table(db, "integration_resources")
            resource_id = await _insert_seed(
                db,
                resource_table,
                workspace_id=workspace_id,
                marker=marker,
                overrides={"connection_id": connection_id},
            )
            group_table = await _reflect_table(db, "integration_context_groups")
            group_id = await _insert_seed(
                db,
                group_table,
                workspace_id=workspace_id,
                marker=marker,
            )
            overrides.update(
                group_id=group_id[0],
                integration_resource_id=resource_id[0],
            )
    return await _insert_seed(
        db,
        table,
        workspace_id=workspace_id,
        marker=marker,
        overrides=overrides,
    )


async def test_runtime_role_is_non_privileged_and_every_policy_is_forced(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with get_maintenance_async_db_session_factory()() as db:
        role = (
            await db.execute(
                sa.text(
                    "SELECT rolsuper, rolcreaterole, rolcreatedb, rolcanlogin, "
                    "rolinherit, rolbypassrls FROM pg_roles WHERE rolname = 'praxis_app'"
                )
            )
        ).one()
        assert tuple(role) == (False, False, False, True, False, False)

        protected = {
            row.relname: (row.relrowsecurity, row.relforcerowsecurity)
            for row in (
                await db.execute(
                    sa.text(
                        "SELECT relname, relrowsecurity, relforcerowsecurity "
                        "FROM pg_class WHERE relname = ANY(:tables)"
                    ),
                    {"tables": list(RLS_TABLES)},
                )
            )
        }
        assert protected == dict.fromkeys(RLS_TABLES, (True, True))
        policy_tables = set(
            (
                await db.scalars(
                    sa.text(
                        "SELECT tablename FROM pg_policies "
                        "WHERE schemaname = 'public' AND tablename = ANY(:tables)"
                    ),
                    {"tables": list(RLS_TABLES)},
                )
            ).all()
        )
        assert policy_tables == set(RLS_TABLES)


async def test_runtime_role_fails_closed_without_tenant_gucs(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = uuid4()
    async with get_maintenance_async_db_session_factory()() as maintenance_db:
        async with maintenance_db.begin_nested():
            await maintenance_db.execute(sa.text("SET LOCAL session_replication_role = replica"))
            agents = await _reflect_table(maintenance_db, "agents")
            await _insert_seed(
                maintenance_db,
                agents,
                workspace_id=workspace_id,
                marker="a",
            )
            await maintenance_db.flush()
            await maintenance_db.execute(sa.text("SET LOCAL session_replication_role = origin"))

        async with db_session_factory() as runtime_db:
            assert (await runtime_db.scalar(sa.select(sa.func.count()).select_from(agents))) == 0
            with pytest.raises(DBAPIError):
                async with runtime_db.begin_nested():
                    await runtime_db.execute(
                        sa.insert(agents).values(
                            _seed_values(
                                agents,
                                workspace_id=workspace_id,
                                marker="blocked",
                            )
                        )
                    )


async def test_ai_usage_ledger_is_runtime_append_only_and_workspace_cascade_safe(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = uuid4()
    async with get_maintenance_async_db_session_factory()() as maintenance_db:
        workspaces = await _reflect_table(maintenance_db, "workspaces")
        events = await _reflect_table(maintenance_db, "ai_usage_events")
        await _insert_seed(
            maintenance_db,
            workspaces,
            workspace_id=workspace_id,
            marker="usage",
            overrides={"id": workspace_id},
        )
        await maintenance_db.commit()

        async with db_session_factory() as runtime_db:
            await set_session_tenant_context(runtime_db, workspace_id=workspace_id)
            event_id = await runtime_db.scalar(
                sa.insert(events)
                .values(
                    id=uuid4(),
                    workspace_id=workspace_id,
                    provider="openai",
                    model="gpt-5.6-luna",
                    purpose="agent_run",
                    requests=1,
                )
                .returning(events.c.id)
            )
            await runtime_db.commit()

            with pytest.raises(DBAPIError):
                async with runtime_db.begin_nested():
                    await runtime_db.execute(
                        sa.update(events).where(events.c.id == event_id).values(requests=2)
                    )
            with pytest.raises(DBAPIError):
                async with runtime_db.begin_nested():
                    await runtime_db.execute(sa.delete(events).where(events.c.id == event_id))

        await maintenance_db.execute(sa.delete(workspaces).where(workspaces.c.id == workspace_id))
        await maintenance_db.commit()
        assert (
            await maintenance_db.scalar(
                sa.select(sa.func.count()).select_from(events).where(events.c.id == event_id)
            )
            == 0
        )


@pytest.mark.parametrize("table_name", RLS_TABLES)
async def test_raw_select_is_blind_to_other_workspace_rows(
    table_name: str,
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workspace_a = uuid4()
    workspace_b = uuid4()
    async with get_maintenance_async_db_session_factory()() as maintenance_db:
        async with maintenance_db.begin_nested():
            await maintenance_db.execute(sa.text("SET LOCAL session_replication_role = replica"))
            table = await _reflect_table(maintenance_db, table_name)
            a_pk = await _seed_protected_row(
                maintenance_db,
                table,
                workspace_id=workspace_a,
                marker="a",
            )
            await _seed_protected_row(
                maintenance_db,
                table,
                workspace_id=workspace_b,
                marker="b",
            )
            await maintenance_db.flush()
            await maintenance_db.execute(sa.text("SET LOCAL session_replication_role = origin"))

        async with db_session_factory() as runtime_db:
            await set_session_tenant_context(runtime_db, workspace_id=workspace_a)
            rows = (await runtime_db.execute(sa.select(table))).all()
            assert len(rows) == 1
            assert tuple(rows[0]._mapping[column.name] for column in table.primary_key) == a_pk


async def test_user_owned_integrations_remain_visible_across_workspaces(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id = uuid4()
    workspace_a = uuid4()
    workspace_b = uuid4()
    async with get_maintenance_async_db_session_factory()() as maintenance_db:
        async with maintenance_db.begin_nested():
            await maintenance_db.execute(sa.text("SET LOCAL session_replication_role = replica"))
            credentials = await _reflect_table(maintenance_db, "external_credentials")
            connections = await _reflect_table(maintenance_db, "integration_connections")
            credential_id = await _insert_seed(
                maintenance_db,
                credentials,
                workspace_id=workspace_a,
                marker="user",
                overrides={"owner_workspace_id": None, "owner_user_id": user_id},
            )
            connection_id = await _insert_seed(
                maintenance_db,
                connections,
                workspace_id=workspace_a,
                marker="user",
                overrides={
                    "credential_id": credential_id[0],
                    "owner_workspace_id": None,
                    "owner_user_id": user_id,
                },
            )
            await maintenance_db.flush()
            await maintenance_db.execute(sa.text("SET LOCAL session_replication_role = origin"))

        for workspace_id in (workspace_a, workspace_b):
            async with db_session_factory() as runtime_db:
                await set_session_tenant_context(
                    runtime_db,
                    workspace_id=workspace_id,
                    user_id=user_id,
                )
                assert (
                    await runtime_db.scalar(
                        sa.select(connections.c.id).where(connections.c.id == connection_id[0])
                    )
                    == connection_id[0]
                )
