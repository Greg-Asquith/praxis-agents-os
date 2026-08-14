# apps/api/services/agent_runs/get_approval_state.py

"""Read the safe pending approval projection for an agent run."""

from uuid import UUID

from pydantic_core import to_jsonable_python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError, NotFoundError
from core.settings import settings
from models.agent_run import AgentRun
from models.user import User
from models.workspace import Workspace
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL
from services.agent_runs.schemas import (
    AgentRunApprovalStateResponse,
    NestedTraceEntryRead,
    PendingDelegatedApprovalRead,
    PendingToolApprovalRead,
    PendingWorkflowStateRead,
    PendingWorkflowToolApprovalRead,
)
from services.agent_runs.utils import load_delegated_child_run_for_approval
from services.agents.delegation_approval import (
    DELEGATED_APPROVAL_CHILD_AGENT_NAME_KEY,
)
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.staged_tool_content import (
    tool_args_for_display,
    tool_replay_args_for_editing,
)
from utils.metadata import metadata_str


async def get_agent_run_approval_state(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    run_id: UUID,
) -> AgentRunApprovalStateResponse:
    """Return pending approval descriptors without exposing run message history."""
    from services.agents.runtime.code_mode.approval import code_mode_nested_call
    from services.agents.runtime.code_mode.state import CodeModeStateError, load_code_mode_state

    run = await db.scalar(
        select(AgentRun).where(
            AgentRun.id == run_id,
            AgentRun.workspace_id == workspace.id,
            AgentRun.user_id == actor.id,
            AgentRun.deleted == False,  # noqa: E712
        )
    )
    if run is None:
        raise NotFoundError(
            "Agent run not found",
            resource_type="agent_run",
            resource_id=str(run_id),
        )

    if run.status != RUN_STATUS_AWAITING_APPROVAL:
        raise ConflictError(
            "Agent run is not awaiting approval",
            conflicting_resource="agent_run",
            details={"run_id": str(run.id), "run_status": run.status},
        )

    suspended_state = load_suspended_run_state(run)
    approvals: list[PendingToolApprovalRead] = []
    delegations: list[PendingDelegatedApprovalRead] = []
    workflow: PendingWorkflowStateRead | None = None
    for approval in suspended_state.deferred_tool_requests.approvals:
        metadata = suspended_state.deferred_tool_requests.metadata.get(approval.tool_call_id)
        nested_call = code_mode_nested_call(metadata)
        if nested_call is not None:
            pending = PendingWorkflowToolApprovalRead(
                tool_call_id=nested_call.tool_call_id,
                name=nested_call.tool_name,
                args=to_jsonable_python(
                    tool_args_for_display(
                        tool_name=nested_call.tool_name,
                        args=nested_call.args,
                        metadata=metadata,
                    )
                ),
                replay_args=to_jsonable_python(
                    tool_replay_args_for_editing(
                        tool_name=nested_call.tool_name,
                        args=nested_call.args,
                    )
                ),
                parent_tool_call_id=approval.tool_call_id,
                derived_from_untrusted=(
                    isinstance(metadata, dict) and metadata.get("derived_from_untrusted") is True
                ),
                taint_sources=_taint_sources(metadata),
            )
            approvals.append(pending)
            try:
                state = load_code_mode_state(
                    run,
                    outer_tool_call_id=approval.tool_call_id,
                    snapshot_max_bytes=settings.AGENT_CODE_MODE_SNAPSHOT_MAX_BYTES,
                )
            except (CodeModeStateError, KeyError, TypeError, ValueError):
                continue
            workflow = PendingWorkflowStateRead(
                outer_tool_call_id=approval.tool_call_id,
                code=state.code,
                reason=state.reason,
                nested_trace=[_trace_entry(item) for item in state.nested_trace],
                trace_truncated=state.trace_truncated,
                pending=pending,
            )
            continue
        child_run = await load_delegated_child_run_for_approval(
            db,
            parent_run=run,
            metadata=metadata,
        )
        if child_run is None:
            approvals.append(
                PendingToolApprovalRead(
                    tool_call_id=approval.tool_call_id,
                    name=approval.tool_name,
                    args=to_jsonable_python(
                        tool_args_for_display(
                            tool_name=approval.tool_name,
                            args=approval.args,
                            metadata=metadata,
                        )
                    ),
                    replay_args=to_jsonable_python(
                        tool_replay_args_for_editing(
                            tool_name=approval.tool_name,
                            args=approval.args,
                        )
                    ),
                )
            )
            continue

        child_state = load_suspended_run_state(child_run)
        delegation = PendingDelegatedApprovalRead(
            parent_tool_call_id=approval.tool_call_id,
            child_agent_id=child_run.agent_id,
            child_agent_name=metadata_str(metadata.get(DELEGATED_APPROVAL_CHILD_AGENT_NAME_KEY))
            or "Delegate agent",
            child_conversation_id=child_run.conversation_id,
            child_run_id=child_run.id,
            pending_approval_count=len(child_state.pending_tool_call_ids),
        )
        delegations.append(delegation)
        approvals.extend(
            PendingToolApprovalRead(
                tool_call_id=child_approval.tool_call_id,
                name=child_approval.tool_name,
                args=to_jsonable_python(
                    tool_args_for_display(
                        tool_name=child_approval.tool_name,
                        args=child_approval.args,
                        metadata=child_state.deferred_tool_requests.metadata.get(
                            child_approval.tool_call_id
                        ),
                    )
                ),
                replay_args=to_jsonable_python(
                    tool_replay_args_for_editing(
                        tool_name=child_approval.tool_name,
                        args=child_approval.args,
                    )
                ),
                delegation=delegation,
            )
            for child_approval in child_state.deferred_tool_requests.approvals
        )

    return AgentRunApprovalStateResponse(
        run_id=run.id,
        conversation_id=run.conversation_id,
        approvals=approvals,
        delegations=delegations,
        workflow=workflow,
    )


def _trace_entry(raw: dict[str, object]) -> NestedTraceEntryRead:
    return NestedTraceEntryRead(
        tool_call_id=str(raw["tool_call_id"]),
        tool_name=str(raw["tool_name"]),
        summary=str(raw.get("summary") or raw["tool_name"]),
        status=str(raw["status"]),  # type: ignore[arg-type]
        result_excerpt=(str(raw["excerpt"]) if raw.get("excerpt") is not None else None),
        position=int(raw.get("order") or raw.get("position") or 1),
    )


def _taint_sources(metadata: object) -> list[dict[str, str]]:
    if not isinstance(metadata, dict) or not isinstance(metadata.get("taint_sources"), list):
        return []
    sources = []
    for item in metadata["taint_sources"]:
        if not isinstance(item, dict):
            continue
        source_kind = item.get("source_kind")
        source_ref = item.get("source_ref")
        if isinstance(source_kind, str) and isinstance(source_ref, str):
            sources.append({"source_kind": source_kind, "source_ref": source_ref})
    return sources
