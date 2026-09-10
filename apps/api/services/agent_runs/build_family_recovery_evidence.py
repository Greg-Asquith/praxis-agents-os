# apps/api/services/agent_runs/build_family_recovery_evidence.py

"""Copies bounded action references before executable approval state is cleared."""

from contextlib import suppress
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from models.agent_run import AgentRun
from models.audit_event import AuditEvent
from services.agent_runs.continuation_state import denied_approval_calls
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.code_mode.approval import code_mode_nested_call
from services.agents.runtime.execution_control import InterruptionReason

RECOVERY_ERROR_CODE = "agent_run_resume_requires_recovery"
RecoveryReason = Literal["execution_interrupted", "child_unavailable", "workflow_state_unavailable"]
MAX_RECOVERY_ACTIONS = 25
MAX_RECOVERY_CHILDREN = 128
# Failure codes that stop execution before the model can observe approved results.
INTERRUPTION_ERROR_CODES = frozenset(
    {
        RECOVERY_ERROR_CODE,
        "code_mode_resume_requires_recovery",
        "delegation_requires_recovery",
        "schedule_execution_abandoned",
        "run_abandoned",
        *(reason.value for reason in InterruptionReason),
    }
)


def recovery_required(*, error_code: str | None, evidence: dict[str, Any]) -> bool:
    """Decides whether a failure leaves approved effects in doubt.

    An interruption always requires review because the model never received the
    approved results. An ordinary failure requires review only when the evidence
    still lists uncertain actions, references it cannot resolve, or was truncated.
    """
    if error_code is None or error_code in INTERRUPTION_ERROR_CODES:
        return True
    recovery = evidence.get("recovery")
    if not isinstance(recovery, dict):
        return True
    if recovery.get("truncated") or recovery.get("unavailable_child_run_ids"):
        return True
    actions = recovery.get("actions")
    if not isinstance(actions, list):
        return True
    return any(
        isinstance(action, dict) and action.get("status") == "uncertain" for action in actions
    )


async def build_family_recovery_evidence(
    db: AsyncSession, *, family: list[AgentRun], reason: RecoveryReason = "execution_interrupted"
) -> dict[str, Any]:
    """Returns safe completed and uncertain references without copying tool payloads."""
    root = family[0]
    actions: dict[tuple[str, str], dict[str, str]] = {}
    saved_evidence_truncated = False
    referenced_children: set[str] = set()
    reservation = (root.metadata_json or {}).get("approval_continuation")
    if isinstance(reservation, dict) and isinstance(reservation.get("child_batches"), dict):
        for child_id in list(reservation["child_batches"])[:1024]:
            try:
                referenced_children.add(str(UUID(str(child_id))))
            except (ValueError, TypeError):
                continue
    for run in family:
        denied_calls = denied_approval_calls(root=root, run=run)
        recovery = (run.completion_json or {}).get("recovery")
        if isinstance(recovery, dict) and recovery.get("truncated") is True:
            saved_evidence_truncated = True
        saved_actions = recovery.get("actions") if isinstance(recovery, dict) else None
        for action in (
            saved_actions[:MAX_RECOVERY_ACTIONS] if isinstance(saved_actions, list) else []
        ):
            if (
                isinstance(action, dict)
                and action.get("owner_run_id") == str(run.id)
                and isinstance(action.get("tool_call_id"), str)
                and isinstance(action.get("tool_name"), str)
                and action.get("status") in {"completed", "uncertain"}
            ):
                key = (str(run.id), action["tool_call_id"][:256])
                actions[key] = {
                    "owner_run_id": key[0],
                    "tool_call_id": key[1],
                    "tool_name": action["tool_name"][:100],
                    "status": action["status"],
                }
        workflow = (run.metadata_json or {}).get("code_mode_state")
        if isinstance(workflow, dict) and workflow.get("run_id") == str(run.id):
            effects = workflow.get("executed_effects")
            for effect in effects[:1024] if isinstance(effects, list) else []:
                if not isinstance(effect, dict):
                    continue
                call_id, name = effect.get("nested_call_id"), effect.get("tool_name")
                if not isinstance(call_id, str) or not isinstance(name, str):
                    continue
                key = (str(run.id), call_id[:256])
                actions[key] = {
                    "owner_run_id": key[0],
                    "tool_call_id": key[1],
                    "tool_name": name[:100],
                    "status": "completed",
                }
        try:
            state = load_suspended_run_state(run)
        except ConflictError:
            continue
        for call in state.deferred_tool_requests.approvals:
            metadata = state.deferred_tool_requests.metadata.get(call.tool_call_id)
            if isinstance(metadata, dict) and metadata.get("kind") == "delegated_child_run":
                with suppress(ValueError, TypeError):
                    referenced_children.add(str(UUID(str(metadata.get("child_run_id")))))
                continue
            leaf = code_mode_nested_call(metadata) or call
            if leaf.tool_call_id in denied_calls:
                continue
            key = (str(run.id), leaf.tool_call_id[:256])
            actions.setdefault(
                key,
                {
                    "owner_run_id": key[0],
                    "tool_call_id": key[1],
                    "tool_name": leaf.tool_name[:100],
                    "status": "uncertain",
                },
            )
    rows = await db.execute(
        select(
            AuditEvent.details["run_id"].astext,
            AuditEvent.resource_id,
            AuditEvent.tool_name,
            AuditEvent.details["outcome"].astext,
        )
        .where(
            AuditEvent.workspace_id == root.workspace_id,
            AuditEvent.actor_user_id == root.user_id,
            AuditEvent.resource_type == "tool_call",
            AuditEvent.details["run_id"].astext.in_([str(run.id) for run in family]),
            AuditEvent.details["outcome"].astext.in_(["completed", "unverified_mutation"]),
        )
        .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id)
        .limit(MAX_RECOVERY_ACTIONS + 1)
    )
    audit_rows = list(rows)
    # Completed audit records supersede uncertainty, including saved workflow leaves.
    for owner, call_id, name, outcome in audit_rows:
        if not call_id or not name:
            continue
        key = (owner, call_id[:256])
        actions[key] = {
            "owner_run_id": owner,
            "tool_call_id": key[1],
            "tool_name": name[:100],
            "status": "completed" if outcome == "completed" else "uncertain",
        }
    ordered = sorted(
        actions.values(),
        key=lambda action: (
            action["status"] != "completed",
            action["owner_run_id"],
            action["tool_call_id"],
        ),
    )
    unavailable_children = sorted(referenced_children - {str(run.id) for run in family})
    return {
        "error_code": RECOVERY_ERROR_CODE,
        "recovery": {
            "reason": reason,
            "root_run_id": str(root.id),
            "root_conversation_id": str(root.conversation_id),
            "children": [
                {"run_id": str(run.id), "conversation_id": str(run.conversation_id)}
                for run in family[1 : MAX_RECOVERY_CHILDREN + 1]
            ],
            "actions": ordered[:MAX_RECOVERY_ACTIONS],
            "unavailable_child_run_ids": unavailable_children[:MAX_RECOVERY_CHILDREN],
            "truncated": (
                saved_evidence_truncated
                or len(ordered) > MAX_RECOVERY_ACTIONS
                or len(audit_rows) > MAX_RECOVERY_ACTIONS
                or len(family) - 1 > MAX_RECOVERY_CHILDREN
                or len(unavailable_children) > MAX_RECOVERY_CHILDREN
            ),
        },
    }
