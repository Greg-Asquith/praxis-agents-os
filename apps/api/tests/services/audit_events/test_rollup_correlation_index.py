"""Measured coverage for indexed audit roll-up correlation lookup."""

import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import String, and_, column, insert, select, text, values
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_maintenance_async_db_session_factory
from models.audit_event import AuditEvent
from services.audit_events.enums import AuditResourceType
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.audit_rollup import (
    MATCHING_GROUPS,
    ROWS_PER_GROUP,
    SOURCE_ROWS,
    UNRELATED_GROUPS,
    audit_rollup_correlation_pair,
    build_audit_rollup_event_rows,
)

_INDEX_NAME = "ix_audit_events_rollup_correlation"


def _lookup_statement(workspace_id: UUID):
    qualified = (
        values(
            column("run_id", String),
            column("tool_call_id", String),
            name="qualified",
        )
        .data(
            [
                audit_rollup_correlation_pair(index)
                for index in range(
                    UNRELATED_GROUPS,
                    UNRELATED_GROUPS + MATCHING_GROUPS,
                )
            ]
        )
        .cte()
    )
    return (
        select(AuditEvent.id)
        .join(
            qualified,
            and_(
                AuditEvent.workspace_id == workspace_id,
                AuditEvent.audit_rollup_run_id == qualified.c.run_id,
                AuditEvent.audit_rollup_tool_call_id == qualified.c.tool_call_id,
            ),
        )
        .where(
            AuditEvent.audit_rollup_run_id.is_not(None),
            AuditEvent.audit_rollup_tool_call_id.is_not(None),
        )
    )


def _plan_nodes(node: dict[str, Any]):
    yield node
    for child in node.get("Plans", []):
        yield from _plan_nodes(child)


async def test_rollup_correlation_lookup_is_indexed_complete_and_workspace_scoped(
    db_session: AsyncSession,
) -> None:
    actor = build_user(email=f"rollup-index-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"rollup-index-{uuid4().hex[:8]}")
    db_session.add_all(
        [
            actor,
            workspace,
            build_workspace_membership(workspace_id=workspace.id, user_id=actor.id),
        ]
    )
    await db_session.flush()
    rows = build_audit_rollup_event_rows(
        workspace_id=workspace.id,
        actor_id=actor.id,
        group_indexes=range(UNRELATED_GROUPS + MATCHING_GROUPS),
    )
    assert len(rows) == SOURCE_ROWS
    await db_session.execute(insert(AuditEvent), rows)

    legacy_ids = [uuid4(), uuid4(), uuid4()]
    await db_session.execute(
        insert(AuditEvent),
        [
            {
                **rows[0],
                "id": legacy_ids[0],
                "resource_id": "legacy-tool-without-run",
                "details": {},
                "audit_rollup_run_id": "caller-supplied-run",
                "audit_rollup_tool_call_id": "caller-supplied-call",
            },
            {
                **rows[0],
                "id": legacy_ids[1],
                "resource_type": AuditResourceType.INTEGRATION_RESOURCE.value,
                "resource_id": "legacy-integration-without-call",
                "details": {"run_id": "legacy-run"},
            },
            {
                **rows[0],
                "id": legacy_ids[2],
                "resource_type": AuditResourceType.AGENT.value,
                "resource_id": "non-correlated-resource",
                "details": {
                    "run_id": "ignored-run",
                    "tool_call_id": "ignored-call",
                },
            },
        ],
    )
    await db_session.commit()

    other_workspace = build_workspace(slug=f"rollup-index-other-{uuid4().hex[:8]}")
    maintenance_factory = get_maintenance_async_db_session_factory()
    async with maintenance_factory() as maintenance_db:
        maintenance_db.add(other_workspace)
        await maintenance_db.flush()
        await maintenance_db.execute(
            insert(AuditEvent),
            build_audit_rollup_event_rows(
                workspace_id=other_workspace.id,
                actor_id=actor.id,
                group_indexes=range(UNRELATED_GROUPS, UNRELATED_GROUPS + 1),
            ),
        )
        await maintenance_db.commit()

    legacy_values = (
        await db_session.execute(
            select(
                AuditEvent.id,
                AuditEvent.audit_rollup_run_id,
                AuditEvent.audit_rollup_tool_call_id,
            ).where(AuditEvent.id.in_(legacy_ids))
        )
    ).all()
    assert len(legacy_values) == len(legacy_ids)
    legacy_by_id = {event_id: (run_id, call_id) for event_id, run_id, call_id in legacy_values}
    assert all(run_id is None or call_id is None for run_id, call_id in legacy_by_id.values())
    assert legacy_by_id == {
        legacy_ids[0]: (None, "legacy-tool-without-run"),
        legacy_ids[1]: ("legacy-run", None),
        legacy_ids[2]: ("ignored-run", None),
    }

    reused_runs = set(
        (
            await db_session.execute(
                select(AuditEvent.audit_rollup_run_id)
                .where(
                    AuditEvent.workspace_id == workspace.id,
                    AuditEvent.audit_rollup_tool_call_id == "plan-148-reused-call",
                )
                .distinct()
            )
        ).scalars()
    )
    assert reused_runs == {"plan-148-run-2008", "plan-148-run-2009"}

    await db_session.execute(text("RESET ROLE"))
    await db_session.execute(text("ANALYZE audit_events"))
    await db_session.execute(text("SET LOCAL ROLE praxis_app"))
    lookup_stmt = _lookup_statement(workspace.id)
    member_ids = set((await db_session.execute(lookup_stmt)).scalars())
    assert len(member_ids) == MATCHING_GROUPS * ROWS_PER_GROUP

    compiled = lookup_stmt.compile(
        dialect=db_session.get_bind().dialect,
        compile_kwargs={"literal_binds": True},
    )
    explain = await db_session.execute(text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {compiled}"))
    [document] = explain.scalar_one()
    plan = document["Plan"]
    indexes = {
        str(node["Index Name"]) for node in _plan_nodes(plan) if node.get("Index Name") is not None
    }
    shared_buffers = int(plan.get("Shared Hit Blocks", 0)) + int(plan.get("Shared Read Blocks", 0))
    summary = {
        "execution_time_ms": float(document["Execution Time"]),
        "indexes": sorted(indexes),
        "member_rows": int(plan["Actual Rows"]),
        "shared_buffers": shared_buffers,
    }
    print(json.dumps(summary, sort_keys=True))  # noqa: T201

    assert plan["Actual Rows"] == MATCHING_GROUPS * ROWS_PER_GROUP
    assert _INDEX_NAME in indexes
    assert shared_buffers <= 283
