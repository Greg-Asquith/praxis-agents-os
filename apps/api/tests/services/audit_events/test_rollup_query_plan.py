"""Measured query-plan coverage for selective audit roll-up ranking."""

import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.audit_event import AuditEvent
from services.audit_events.queries import _rolled_up_audit_events_statement
from tests.factories import build_user, build_workspace, build_workspace_membership
from tests.support.audit_rollup import (
    MATCHING_GROUPS,
    ROWS_PER_GROUP,
    SOURCE_ROWS,
    UNRELATED_GROUPS,
    build_audit_rollup_event_rows,
)

_PRE_INDEX_BROAD_BASELINE_BUFFERS = 572
_PRE_INDEX_NARROW_BASELINE_BUFFERS = 566
_INDEX_NAME = "ix_audit_events_rollup_correlation"


def _plan_nodes(node: dict[str, Any]):
    yield node
    for child in node.get("Plans", []):
        yield from _plan_nodes(child)


async def _explain_summary(
    db_session: AsyncSession,
    *,
    workspace_id: UUID,
    tool_name: str | None,
) -> dict[str, Any]:
    stmt = _rolled_up_audit_events_statement(
        workspace_id=workspace_id,
        tool_name=tool_name,
    )
    compiled = stmt.compile(
        dialect=db_session.get_bind().dialect,
        compile_kwargs={"literal_binds": True},
    )
    explained = await db_session.execute(
        text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {compiled}")
    )
    [document] = explained.scalar_one()
    plan = document["Plan"]
    nodes = list(_plan_nodes(plan))
    window_rows = [int(node["Actual Rows"]) for node in nodes if node["Node Type"] == "WindowAgg"]
    indexes = {str(node["Index Name"]) for node in nodes if node.get("Index Name") is not None}
    return {
        "execution_time_ms": float(document["Execution Time"]),
        "indexes": sorted(indexes),
        "ranked_input_rows": max(window_rows),
        "shared_buffers": int(plan.get("Shared Hit Blocks", 0))
        + int(plan.get("Shared Read Blocks", 0)),
    }


async def test_selective_rollup_prefilters_complete_members_before_ranking(
    db_session: AsyncSession,
) -> None:
    actor = build_user(email=f"rollup-plan-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"rollup-plan-{uuid4().hex[:8]}")
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
    await db_session.commit()

    await db_session.execute(text("RESET ROLE"))
    await db_session.execute(text("ANALYZE audit_events"))
    await db_session.execute(text("SET LOCAL ROLE praxis_app"))
    relation_blocks = int(
        (
            await db_session.execute(
                text(
                    "SELECT pg_relation_size('audit_events') "
                    "/ current_setting('block_size')::integer"
                )
            )
        ).scalar_one()
    )
    current_broad_baseline_buffers = relation_blocks

    broad = await _explain_summary(
        db_session,
        workspace_id=workspace.id,
        tool_name=None,
    )
    narrow = await _explain_summary(
        db_session,
        workspace_id=workspace.id,
        tool_name="plan_148_matching",
    )
    print(  # noqa: T201
        json.dumps(
            {
                "baseline": {
                    "broad": {
                        "ranked_input_rows": SOURCE_ROWS,
                        "shared_buffers_before_index": _PRE_INDEX_BROAD_BASELINE_BUFFERS,
                        "shared_buffers_current_schema": current_broad_baseline_buffers,
                    },
                    "narrow": {
                        "ranked_input_rows": SOURCE_ROWS,
                        "shared_buffers": _PRE_INDEX_NARROW_BASELINE_BUFFERS,
                    },
                },
                "optimized": {"broad": broad, "narrow": narrow},
            },
            sort_keys=True,
        )
    )

    assert broad["ranked_input_rows"] == SOURCE_ROWS
    assert narrow["ranked_input_rows"] == MATCHING_GROUPS * ROWS_PER_GROUP
    assert _INDEX_NAME in narrow["indexes"]
    assert narrow["shared_buffers"] <= _PRE_INDEX_NARROW_BASELINE_BUFFERS * 0.5
    assert broad["shared_buffers"] <= current_broad_baseline_buffers * 1.1
