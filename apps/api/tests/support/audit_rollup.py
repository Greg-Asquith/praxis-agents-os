"""Deterministic audit roll-up fixtures shared by query-plan tests."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from services.audit_events.enums import (
    AuditAction,
    AuditActorType,
    AuditResourceType,
    AuditStatus,
)

UNRELATED_GROUPS = 2_000
MATCHING_GROUPS = 10
ROWS_PER_GROUP = 3
SOURCE_ROWS = (UNRELATED_GROUPS + MATCHING_GROUPS) * ROWS_PER_GROUP


def audit_rollup_correlation_pair(index: int) -> tuple[str, str]:
    call_id = "plan-148-reused-call" if index >= 2_008 else f"plan-148-call-{index}"
    return f"plan-148-run-{index}", call_id


def build_audit_rollup_event_rows(
    *,
    workspace_id: UUID,
    actor_id: UUID,
    group_indexes: range,
) -> list[dict[str, Any]]:
    base_time = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    rows: list[dict[str, Any]] = []
    for index in group_indexes:
        run_id, call_id = audit_rollup_correlation_pair(index)
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
        occurred_at = base_time + timedelta(microseconds=index * ROWS_PER_GROUP)
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
