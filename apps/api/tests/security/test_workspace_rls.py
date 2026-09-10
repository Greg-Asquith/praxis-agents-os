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
    "integration_table_scope_rules",
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
        ("integration_table_scope_rules", "column_type"): "string",
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
        if table.name in {"integration_table_schemas", "integration_table_scope_rules"}:
            resource_table = await _reflect_table(db, "integration_resources")
            resource_id = await _insert_seed(
                db,
                resource_table,
                workspace_id=workspace_id,
                marker=marker,
                overrides={"connection_id": connection_id},
            )
            overrides["resource_id"] = resource_id[0]
            if table.name == "integration_table_scope_rules":
                overrides["allowed_values"] = ["client-1"]
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


async def test_platform_skills_are_runtime_read_only_across_workspaces(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workspace_a = uuid4()
    workspace_b = uuid4()
    platform_skill_id = uuid4()
    async with get_maintenance_async_db_session_factory()() as maintenance_db:
        async with maintenance_db.begin_nested():
            await maintenance_db.execute(sa.text("SET LOCAL session_replication_role = replica"))
            skills = await _reflect_table(maintenance_db, "skills")
            await _insert_seed(
                maintenance_db,
                skills,
                workspace_id=workspace_a,
                marker="platform",
                overrides={
                    "id": platform_skill_id,
                    "scope": "platform",
                    "workspace_id": None,
                    "name": "platform-rls-test",
                },
            )
            await maintenance_db.flush()
            await maintenance_db.execute(sa.text("SET LOCAL session_replication_role = origin"))

        for workspace_id in (workspace_a, workspace_b):
            async with db_session_factory() as runtime_db:
                await set_session_tenant_context(runtime_db, workspace_id=workspace_id)
                assert (
                    await runtime_db.scalar(
                        sa.select(skills.c.id).where(skills.c.id == platform_skill_id)
                    )
                    == platform_skill_id
                )

        async with db_session_factory() as runtime_db:
            await set_session_tenant_context(runtime_db, workspace_id=workspace_a)
            blocked_values = _seed_values(
                skills,
                workspace_id=workspace_a,
                marker="blocked-platform",
                overrides={"scope": "platform", "workspace_id": None},
            )
            with pytest.raises(DBAPIError):
                async with runtime_db.begin_nested():
                    await runtime_db.execute(sa.insert(skills).values(**blocked_values))

            update_result = await runtime_db.execute(
                sa.update(skills)
                .where(skills.c.id == platform_skill_id)
                .values(description="Runtime mutation")
            )
            delete_result = await runtime_db.execute(
                sa.delete(skills).where(skills.c.id == platform_skill_id)
            )
            assert update_result.rowcount == 0
            assert delete_result.rowcount == 0

        assert (
            await maintenance_db.scalar(
                sa.select(skills.c.description).where(skills.c.id == platform_skill_id)
            )
            != "Runtime mutation"
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


PLATFORM_FAMILIES = (
    ("kb_documents", "kb_chunks", "document_id", None, None),
    ("files", "file_revisions", "file_id", "current_revision_id", "published_revision_id"),
    (
        "artifacts",
        "artifact_revisions",
        "artifact_id",
        "current_version_id",
        "published_version_id",
    ),
)
PLATFORM_TABLES = tuple(name for family in PLATFORM_FAMILIES for name in family[:2])


async def _seed_resource_family(db, family, *, workspace_id, scope="platform"):
    parent_name, child_name, parent_key, current_key, published_key = family
    parent = await _reflect_table(db, parent_name)
    child = await _reflect_table(db, child_name)
    ownership = {"scope": scope, "workspace_id": workspace_id if scope == "workspace" else None}
    parent_values = dict(ownership)
    if parent_name == "kb_documents":
        parent_values.update(status="ready", content_md="Published knowledge")
    parent_id = (
        await _insert_seed(
            db, parent, workspace_id=workspace_id, marker="parent", overrides=parent_values
        )
    )[0]
    child_ids = []
    for number in (1, 2, 3):
        values = {**ownership, parent_key: parent_id}
        values["chunk_index" if child_name == "kb_chunks" else "revision_number"] = number
        if scope == "platform":
            values["is_published"] = number < 3
        child_ids.append(
            (
                await _insert_seed(
                    db, child, workspace_id=workspace_id, marker="child", overrides=values
                )
            )[0]
        )
    updates = {"is_published": scope == "platform"}
    if current_key:
        updates[current_key] = child_ids[2]
        updates[published_key] = child_ids[1] if scope == "platform" else None
    await db.execute(sa.update(parent).where(parent.c.id == parent_id).values(**updates))
    return parent, child, parent_id, child_ids


@pytest.mark.parametrize("family", PLATFORM_FAMILIES, ids=lambda family: family[0])
async def test_platform_resources_are_runtime_read_only_across_workspaces(
    family, db_session_factory
):
    workspace_a, workspace_b = uuid4(), uuid4()
    async with get_maintenance_async_db_session_factory()() as db:
        parent, child, parent_id, child_ids = await _seed_resource_family(
            db, family, workspace_id=workspace_a
        )
        for workspace_id in (workspace_a, workspace_b, None):
            async with db_session_factory() as runtime:
                await set_session_tenant_context(runtime, workspace_id=workspace_id)
                visible_parent = await runtime.scalar(
                    sa.select(parent.c.id).where(parent.c.id == parent_id)
                )
                assert visible_parent == (parent_id if workspace_id else None)
                visible_children = set(
                    (
                        await runtime.scalars(
                            sa.select(child.c.id).where(child.c.id.in_(child_ids))
                        )
                    ).all()
                )
                expected = child_ids if child.name == "kb_chunks" else child_ids[:2]
                assert visible_children == (set(expected) if workspace_id else set())
                for table, row_id in ((parent, parent_id), (child, child_ids[0])):
                    for operation in (
                        sa.update(table).where(table.c.id == row_id).values(is_published=False),
                        sa.delete(table).where(table.c.id == row_id),
                    ):
                        assert (await runtime.execute(operation)).rowcount == 0
                    values = _seed_values(
                        table,
                        workspace_id=workspace_a,
                        marker="denied",
                        overrides={"scope": "platform", "workspace_id": None, family[2]: parent_id}
                        if table is child
                        else {"scope": "platform", "workspace_id": None},
                    )
                    with pytest.raises(DBAPIError):
                        async with runtime.begin_nested():
                            await runtime.execute(sa.insert(table).values(**values))

        for updates in ({"is_published": False}, {"is_published": True, "deleted": True}):
            await db.execute(sa.update(parent).where(parent.c.id == parent_id).values(**updates))
            for workspace_id in (workspace_a, workspace_b):
                async with db_session_factory() as runtime:
                    await set_session_tenant_context(runtime, workspace_id=workspace_id)
                    assert (
                        await runtime.scalar(sa.select(parent.c.id).where(parent.c.id == parent_id))
                        is None
                    )
                    assert not (
                        await runtime.scalars(
                            sa.select(child.c.id).where(child.c.id.in_(child_ids))
                        )
                    ).all()


@pytest.mark.parametrize("table_name", (*PLATFORM_TABLES, "file_uploads"))
async def test_platform_resource_owner_constraints_reject_invalid_pairs(
    table_name, db_session_factory
):
    async with get_maintenance_async_db_session_factory()() as db:
        table = await _reflect_table(db, table_name)
        for overrides in (
            {"scope": "platform", "workspace_id": uuid4()},
            {"scope": "workspace", "workspace_id": None},
            {"scope": "unknown", "workspace_id": None},
        ):
            with pytest.raises(DBAPIError):
                async with db.begin_nested():
                    await db.execute(sa.text("SET LOCAL session_replication_role = replica"))
                    await _insert_seed(
                        db, table, workspace_id=uuid4(), marker="invalid", overrides=overrides
                    )


@pytest.mark.parametrize("family", PLATFORM_FAMILIES, ids=lambda family: family[0])
async def test_platform_resource_parent_and_owner_changes_are_rejected(family, db_session_factory):
    workspace_id = uuid4()
    async with get_maintenance_async_db_session_factory()() as db:
        workspaces = await _reflect_table(db, "workspaces")
        other_workspace = uuid4()
        for owner in (workspace_id, other_workspace):
            await _insert_seed(
                db, workspaces, workspace_id=owner, marker="owner", overrides={"id": owner}
            )
        parent, child, parent_id, child_ids = await _seed_resource_family(
            db, family, workspace_id=workspace_id
        )
        _, _, local_parent_id, local_child_ids = await _seed_resource_family(
            db, family, workspace_id=workspace_id, scope="workspace"
        )
        _, _, other_parent_id, other_child_ids = await _seed_resource_family(
            db, family, workspace_id=other_workspace, scope="workspace"
        )
        statements = [
            sa.update(parent)
            .where(parent.c.id == parent_id)
            .values(scope="workspace", workspace_id=workspace_id, is_published=False),
            sa.update(parent)
            .where(parent.c.id == local_parent_id)
            .values(workspace_id=other_workspace),
            sa.update(parent).where(parent.c.id == local_parent_id).values(is_published=True),
            sa.update(child)
            .where(child.c.id == child_ids[0])
            .values(**{family[2]: local_parent_id}),
            sa.update(child)
            .where(child.c.id == local_child_ids[0])
            .values(**{family[2]: other_parent_id}),
            sa.update(child)
            .where(child.c.id == local_child_ids[0])
            .values(workspace_id=other_workspace),
        ]
        if family[3]:
            statements.extend(
                [
                    sa.update(parent)
                    .where(parent.c.id == parent_id)
                    .values(**{family[3]: local_child_ids[0]}),
                    sa.update(parent)
                    .where(parent.c.id == local_parent_id)
                    .values(**{family[3]: other_child_ids[0]}),
                    sa.update(parent)
                    .where(parent.c.id == parent_id)
                    .values(**{family[4]: child_ids[2]}),
                    sa.update(parent)
                    .where(parent.c.id == parent_id)
                    .values(**{family[4]: local_child_ids[0]}),
                    sa.update(child)
                    .where(child.c.id == child_ids[2])
                    .values(revision_kind="restore", restored_from_revision_id=local_child_ids[0]),
                    sa.update(child)
                    .where(child.c.id == local_child_ids[2])
                    .values(revision_kind="restore", restored_from_revision_id=other_child_ids[0]),
                ]
            )
        for statement in statements:
            with pytest.raises(DBAPIError):
                async with db.begin_nested():
                    await db.execute(statement)
                    await db.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))


@pytest.mark.parametrize("family", PLATFORM_FAMILIES, ids=lambda family: family[0])
async def test_platform_resource_insert_rejects_mismatched_parents(family, db_session_factory):
    workspace_id = uuid4()
    async with get_maintenance_async_db_session_factory()() as db:
        workspaces = await _reflect_table(db, "workspaces")
        await _insert_seed(
            db,
            workspaces,
            workspace_id=workspace_id,
            marker="owner",
            overrides={"id": workspace_id},
        )
        _, child, platform_parent_id, platform_children = await _seed_resource_family(
            db, family, workspace_id=workspace_id
        )
        _, _, workspace_parent_id, workspace_children = await _seed_resource_family(
            db, family, workspace_id=workspace_id, scope="workspace"
        )
        parent, _, _, other_platform_children = await _seed_resource_family(
            db, family, workspace_id=workspace_id
        )
        if family[3]:
            for pointer in (family[3], family[4]):
                with pytest.raises(DBAPIError, match="Revision pointer"):
                    async with db.begin_nested():
                        await db.execute(
                            sa.update(parent)
                            .where(parent.c.id == platform_parent_id)
                            .values(**{pointer: other_platform_children[0]})
                        )
        invalid_values = [
            {"scope": "workspace", "workspace_id": workspace_id, family[2]: platform_parent_id},
            {"scope": "platform", "workspace_id": None, family[2]: workspace_parent_id},
        ]
        if family[3]:
            invalid_values.extend(
                [
                    {
                        "scope": "platform",
                        "workspace_id": None,
                        family[2]: platform_parent_id,
                        "revision_kind": "restore",
                        "restored_from_revision_id": workspace_children[0],
                    },
                    {
                        "scope": "platform",
                        "workspace_id": None,
                        family[2]: platform_parent_id,
                        "revision_kind": "restore",
                        "restored_from_revision_id": other_platform_children[0],
                    },
                    {
                        "scope": "workspace",
                        "workspace_id": workspace_id,
                        family[2]: workspace_parent_id,
                        "revision_kind": "restore",
                        "restored_from_revision_id": platform_children[0],
                    },
                ]
            )
        for overrides in invalid_values:
            overrides["chunk_index" if child.name == "kb_chunks" else "revision_number"] = 4
            with pytest.raises(DBAPIError):
                async with db.begin_nested():
                    await _insert_seed(
                        db,
                        child,
                        workspace_id=workspace_id,
                        marker="invalid-parent",
                        overrides=overrides,
                    )
                    await db.execute(sa.text("SET CONSTRAINTS ALL IMMEDIATE"))


async def test_platform_upload_grants_are_hidden_and_runtime_read_only(db_session_factory):
    async with get_maintenance_async_db_session_factory()() as db:
        uploads = await _reflect_table(db, "file_uploads")
        await db.execute(sa.text("SET LOCAL session_replication_role = replica"))
        upload_id = (
            await _insert_seed(
                db,
                uploads,
                workspace_id=uuid4(),
                marker="platform-upload",
                overrides={"scope": "platform", "workspace_id": None},
            )
        )[0]
        await db.execute(sa.text("SET LOCAL session_replication_role = origin"))
        for workspace_id in (uuid4(), uuid4(), None):
            async with db_session_factory() as runtime:
                await set_session_tenant_context(runtime, workspace_id=workspace_id)
                assert (
                    await runtime.scalar(sa.select(uploads.c.id).where(uploads.c.id == upload_id))
                    is None
                )
                assert (
                    await runtime.execute(
                        sa.update(uploads)
                        .where(uploads.c.id == upload_id)
                        .values(filename="changed")
                    )
                ).rowcount == 0
                assert (
                    await runtime.execute(sa.delete(uploads).where(uploads.c.id == upload_id))
                ).rowcount == 0
                with pytest.raises(DBAPIError):
                    async with runtime.begin_nested():
                        await _insert_seed(
                            runtime,
                            uploads,
                            workspace_id=uuid4(),
                            marker="denied-upload",
                            overrides={"scope": "platform", "workspace_id": None},
                        )


@pytest.mark.parametrize("family", PLATFORM_FAMILIES[1:], ids=lambda family: family[0])
async def test_platform_revision_publication_preserves_orm_immutability(family, db_session_factory):
    from models.artifacts import ArtifactRevision
    from models.files import FileRevision

    model = FileRevision if family[0] == "files" else ArtifactRevision
    async with get_maintenance_async_db_session_factory()() as db:
        _, _, _, children = await _seed_resource_family(db, family, workspace_id=uuid4())
        revision = await db.get(model, children[2])
        revision.is_published = True
        await db.flush()
        assert revision.is_published is True
        for attribute, value in (("is_published", False), ("object_key", "rewritten")):
            with pytest.raises(RuntimeError, match="immutable"):
                async with db.begin_nested():
                    revision = await db.get(model, children[2])
                    setattr(revision, attribute, value)
                    await db.flush()


async def test_platform_content_keeps_upload_targets_and_consuming_references_local(
    db_session_factory,
):
    workspace_id, other_workspace = uuid4(), uuid4()
    async with get_maintenance_async_db_session_factory()() as db:
        files, _, file_id, revisions = await _seed_resource_family(
            db, PLATFORM_FAMILIES[1], workspace_id=workspace_id
        )
        _, _, artifact_id, versions = await _seed_resource_family(
            db, PLATFORM_FAMILIES[2], workspace_id=workspace_id
        )
        uploads = await _reflect_table(db, "file_uploads")
        references = await _reflect_table(db, "file_references")
        shares = await _reflect_table(db, "artifact_shares")
        conversations = await _reflect_table(db, "conversations")
        folders = await _reflect_table(db, "file_folders")
        await db.execute(sa.text("SET LOCAL session_replication_role = replica"))
        upload_id = (
            await _insert_seed(
                db,
                uploads,
                workspace_id=workspace_id,
                marker="upload",
                overrides={"scope": "platform", "workspace_id": None},
            )
        )[0]
        targets = []
        for owner in (workspace_id, other_workspace):
            workspaces = await _reflect_table(db, "workspaces")
            await _insert_seed(
                db, workspaces, workspace_id=owner, marker="owner", overrides={"id": owner}
            )
            targets.append(
                (await _insert_seed(db, conversations, workspace_id=owner, marker="target"))[0]
            )
        folder_id = (await _insert_seed(db, folders, workspace_id=workspace_id, marker="folder"))[0]
        await db.execute(sa.text("SET LOCAL session_replication_role = origin"))
        reference_id = (
            await _insert_seed(
                db,
                references,
                workspace_id=workspace_id,
                marker="reference",
                overrides={
                    "file_id": file_id,
                    "file_revision_id": revisions[0],
                    "target_id": targets[0],
                },
            )
        )[0]
        for values in (
            {"scope": "workspace", "workspace_id": workspace_id},
            {"file_id": file_id},
            {"revision_id": uuid4()},
        ):
            with pytest.raises(DBAPIError):
                async with db.begin_nested():
                    await db.execute(
                        sa.update(uploads).where(uploads.c.id == upload_id).values(**values)
                    )
        invalid_inserts = (
            (shares, {"artifact_id": artifact_id, "version_id": versions[0]}),
            (
                references,
                {"file_id": file_id, "file_revision_id": revisions[0], "target_id": targets[1]},
            ),
            (
                references,
                {
                    "file_id": file_id,
                    "file_revision_id": revisions[2],
                    "target_id": targets[0],
                },
            ),
        )
        for table, values in invalid_inserts:
            with pytest.raises(DBAPIError):
                async with db.begin_nested():
                    await _insert_seed(
                        db, table, workspace_id=workspace_id, marker="denied", overrides=values
                    )
        with pytest.raises(DBAPIError):
            async with db.begin_nested():
                await db.execute(
                    sa.update(files).where(files.c.id == file_id).values(folder_id=folder_id)
                )
        for owner in (workspace_id, other_workspace, None):
            async with db_session_factory() as runtime:
                await set_session_tenant_context(runtime, workspace_id=owner)
                statement = sa.select(references.c.id).where(references.c.id == reference_id)
                if owner is None:
                    # The unchanged reference policy rejects an empty UUID context.
                    with pytest.raises(DBAPIError, match="invalid input syntax for type uuid"):
                        async with runtime.begin_nested():
                            await runtime.scalar(statement)
                else:
                    assert await runtime.scalar(statement) == (
                        reference_id if owner == workspace_id else None
                    )


async def test_platform_upload_target_check_ignores_temporary_table_shadowing(db_session_factory):
    workspace_id = uuid4()
    async with get_maintenance_async_db_session_factory()() as db:
        _, _, platform_file_id, _ = await _seed_resource_family(
            db, PLATFORM_FAMILIES[1], workspace_id=workspace_id
        )
        uploads = await _reflect_table(db, "file_uploads")
        await db.execute(
            sa.text("CREATE TEMP TABLE files (LIKE public.files INCLUDING DEFAULTS) ON COMMIT DROP")
        )
        async with db_session_factory() as runtime:
            await set_session_tenant_context(runtime, workspace_id=workspace_id)
            with pytest.raises(DBAPIError, match="Upload target ownership does not match"):
                async with runtime.begin_nested():
                    await _insert_seed(
                        runtime,
                        uploads,
                        workspace_id=workspace_id,
                        marker="shadowed",
                        overrides={"file_id": platform_file_id},
                    )


async def test_platform_upload_reservation_rejects_file_creation_by_another_owner(
    db_session_factory,
):
    workspace_id, reserved_file_id, reserved_revision_id = uuid4(), uuid4(), uuid4()
    async with get_maintenance_async_db_session_factory()() as db:
        workspaces = await _reflect_table(db, "workspaces")
        await _insert_seed(
            db,
            workspaces,
            workspace_id=workspace_id,
            marker="owner",
            overrides={"id": workspace_id},
        )
        uploads = await _reflect_table(db, "file_uploads")
        files = await _reflect_table(db, "files")
        await db.execute(sa.text("SET LOCAL session_replication_role = replica"))
        await _insert_seed(
            db,
            uploads,
            workspace_id=workspace_id,
            marker="reserved",
            overrides={
                "scope": "platform",
                "workspace_id": None,
                "file_id": reserved_file_id,
                "revision_id": reserved_revision_id,
            },
        )
        await db.execute(sa.text("SET LOCAL session_replication_role = origin"))
        async with db_session_factory() as runtime:
            await set_session_tenant_context(runtime, workspace_id=workspace_id)
            with pytest.raises(DBAPIError, match=r"[Uu]pload"):
                async with runtime.begin_nested():
                    await _insert_seed(
                        runtime,
                        files,
                        workspace_id=workspace_id,
                        marker="reserved",
                        overrides={"id": reserved_file_id},
                    )

        _, revisions, local_file_id, _ = await _seed_resource_family(
            db, PLATFORM_FAMILIES[1], workspace_id=workspace_id, scope="workspace"
        )
        async with db_session_factory() as runtime:
            await set_session_tenant_context(runtime, workspace_id=workspace_id)
            with pytest.raises(DBAPIError, match=r"[Uu]pload"):
                async with runtime.begin_nested():
                    await _insert_seed(
                        runtime,
                        revisions,
                        workspace_id=workspace_id,
                        marker="reserved",
                        overrides={
                            "id": reserved_revision_id,
                            "file_id": local_file_id,
                            "revision_number": 4,
                        },
                    )


@pytest.mark.parametrize("target_key", ("file_id", "revision_id"))
async def test_platform_upload_grants_reject_conflicting_reservations(
    target_key, db_session_factory
):
    workspace_id = uuid4()
    async with get_maintenance_async_db_session_factory()() as db:
        workspaces = await _reflect_table(db, "workspaces")
        await _insert_seed(
            db,
            workspaces,
            workspace_id=workspace_id,
            marker="owner",
            overrides={"id": workspace_id},
        )
        users = await _reflect_table(db, "users")
        user_id = (await _insert_seed(db, users, workspace_id=workspace_id, marker="creator"))[0]
        uploads = await _reflect_table(db, "file_uploads")
        target_id = uuid4()
        await _insert_seed(
            db,
            uploads,
            workspace_id=workspace_id,
            marker="platform-reservation",
            overrides={
                "scope": "platform",
                "workspace_id": None,
                "created_by_user_id": user_id,
                target_key: target_id,
            },
        )
        async with db_session_factory() as runtime:
            await set_session_tenant_context(runtime, workspace_id=workspace_id)
            with pytest.raises(DBAPIError, match=r"[Uu]pload"):
                async with runtime.begin_nested():
                    await _insert_seed(
                        runtime,
                        uploads,
                        workspace_id=workspace_id,
                        marker="conflict",
                        overrides={"created_by_user_id": user_id, target_key: target_id},
                    )


@pytest.mark.parametrize("table_name", ("files", "file_uploads"))
async def test_platform_upload_identity_inserts_reject_repeatable_read(
    table_name, committed_db_session_factory
):
    async with get_maintenance_async_db_session_factory()() as db:
        await db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        table = await _reflect_table(db, table_name)
        with pytest.raises(DBAPIError, match="READ COMMITTED"):
            async with db.begin_nested():
                await _insert_seed(
                    db,
                    table,
                    workspace_id=uuid4(),
                    marker="snapshot",
                    overrides={"scope": "platform", "workspace_id": None},
                )


async def test_platform_upload_reservation_serialises_concurrent_file_creation(
    committed_db_session_factory,
):
    import asyncio

    workspace_id, file_id = uuid4(), uuid4()
    maintenance = get_maintenance_async_db_session_factory()
    async with maintenance() as setup:
        workspaces = await _reflect_table(setup, "workspaces")
        users = await _reflect_table(setup, "users")
        files = await _reflect_table(setup, "files")
        uploads = await _reflect_table(setup, "file_uploads")
        await _insert_seed(
            setup,
            workspaces,
            workspace_id=workspace_id,
            marker="race",
            overrides={"id": workspace_id},
        )
        user_id = (await _insert_seed(setup, users, workspace_id=workspace_id, marker="race"))[0]
        await setup.commit()
    started = asyncio.Event()
    second_pid = None

    async def create_conflicting_file():
        nonlocal second_pid
        async with committed_db_session_factory() as runtime:
            await set_session_tenant_context(runtime, workspace_id=workspace_id)
            second_pid = await runtime.scalar(sa.text("SELECT pg_backend_pid()"))
            started.set()
            with pytest.raises(DBAPIError, match=r"[Uu]pload"):
                await _insert_seed(
                    runtime,
                    files,
                    workspace_id=workspace_id,
                    marker="race",
                    overrides={"id": file_id},
                )

    task = None
    upload_id = None
    try:
        async with maintenance() as first:
            upload_id = (
                await _insert_seed(
                    first,
                    uploads,
                    workspace_id=workspace_id,
                    marker="race",
                    overrides={
                        "scope": "platform",
                        "workspace_id": None,
                        "file_id": file_id,
                        "created_by_user_id": user_id,
                    },
                )
            )[0]
            task = asyncio.create_task(create_conflicting_file())
            try:
                async with asyncio.timeout(10):
                    await started.wait()
                    while not await first.scalar(
                        sa.text(
                            "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid = :pid AND locktype = 'advisory' AND NOT granted)"
                        ),
                        {"pid": second_pid},
                    ):
                        if task.done():
                            await task
                            pytest.fail(
                                "The conflicting insert did not wait for the upload reservation"
                            )
                    await first.commit()
                    await task
                    assert (
                        await first.scalar(sa.select(files.c.id).where(files.c.id == file_id))
                        is None
                    )
                    assert (
                        await first.scalar(
                            sa.select(uploads.c.scope).where(uploads.c.id == upload_id)
                        )
                        == "platform"
                    )
            finally:
                await first.rollback()
    finally:
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        async with maintenance() as cleanup:
            if upload_id is not None:
                await cleanup.execute(sa.delete(uploads).where(uploads.c.id == upload_id))
            await cleanup.execute(sa.delete(users).where(users.c.id == user_id))
            await cleanup.execute(sa.delete(workspaces).where(workspaces.c.id == workspace_id))
            await cleanup.commit()
