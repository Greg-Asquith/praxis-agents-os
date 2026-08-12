"""Measured coverage for indexed audit roll-up correlation lookup."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import String, and_, column, insert, select, text, values
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_maintenance_async_db_session_factory
from models.audit_event import AuditEvent
from services.audit_events.enums import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    AuditStatus,
)
from tests.factories import build_user, build_workspace, build_workspace_membership

_UNRELATED_GROUPS = 2_000
_MATCHING_GROUPS = 10
_ROWS_PER_GROUP = 3
_SOURCE_ROWS = (_UNRELATED_GROUPS + _MATCHING_GROUPS) * _ROWS_PER_GROUP
_INDEX_NAME = "ix_audit_events_rollup_correlation"


def _correlation_pair(index: int) -> tuple[str, str]:
    call_id = "plan-148-reused-call" if index >= 2_008 else f"plan-148-call-{index}"
    return f"plan-148-run-{index}", call_id


def _event_rows(
    *,
    workspace_id: UUID,
    actor_id: UUID,
    group_indexes: range,
) -> list[dict[str, Any]]:
    base_time = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    rows: list[dict[str, Any]] = []
    for index in group_indexes:
        run_id, call_id = _correlation_pair(index)
        common = {
            "workspace_id": workspace_id,
            "action": AuditAction.EXECUTE.value,
            "summary": "Audit roll-up correlation fixture",
            "tool_name": "plan_148_matching" if index >= 2_000 else "plan_148_unrelated",
            "tool_provider": "query_plan",
            "actor_type": AuditActorType.USER.value,
            "actor_id": str(actor_id),
            "actor_user_id": actor_id,
            "requested_by_user_id": actor_id,
            "request_id": f"req-{workspace_id}-{index}",
        }
        occurred_at = base_time + timedelta(microseconds=index * _ROWS_PER_GROUP)
        rows.extend(
            (
                {
                    **common,
                    "occurred_at": occurred_at,
                    "resource_type": AuditResourceType.TOOL_CALL.value,
                    "resource_id": call_id,
                    "status": AuditStatus.PENDING.value,
                    "details": {"run_id": run_id},
                },
                {
                    **common,
                    "occurred_at": occurred_at + timedelta(microseconds=2),
                    "resource_type": AuditResourceType.TOOL_CALL.value,
                    "resource_id": call_id,
                    "status": AuditStatus.SUCCESS.value,
                    "details": {"run_id": run_id},
                },
                {
                    **common,
                    "occurred_at": occurred_at + timedelta(microseconds=1),
                    "resource_type": AuditResourceType.INTEGRATION_RESOURCE.value,
                    "resource_id": f"resource-{workspace_id}-{index}",
                    "status": AuditStatus.SUCCESS.value,
                    "details": {"run_id": run_id, "tool_call_id": call_id},
                },
            )
        )
    return rows


def _lookup_statement(workspace_id: UUID):
    qualified = (
        values(
            column("run_id", String),
            column("tool_call_id", String),
            name="qualified",
        )
        .data(
            [
                _correlation_pair(index)
                for index in range(
                    _UNRELATED_GROUPS,
                    _UNRELATED_GROUPS + _MATCHING_GROUPS,
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
    rows = _event_rows(
        workspace_id=workspace.id,
        actor_id=actor.id,
        group_indexes=range(_UNRELATED_GROUPS + _MATCHING_GROUPS),
    )
    assert len(rows) == _SOURCE_ROWS
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
            _event_rows(
                workspace_id=other_workspace.id,
                actor_id=actor.id,
                group_indexes=range(_UNRELATED_GROUPS, _UNRELATED_GROUPS + 1),
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
    assert len(member_ids) == _MATCHING_GROUPS * _ROWS_PER_GROUP

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

    assert plan["Actual Rows"] == _MATCHING_GROUPS * _ROWS_PER_GROUP
    assert _INDEX_NAME in indexes
    assert shared_buffers <= 283
