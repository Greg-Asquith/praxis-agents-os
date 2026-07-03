# apps/api/services/agent_runs/resume_run_stream.py

"""Resume a suspended agent run and stream the continuation."""

from uuid import UUID

from fastapi import Request
from fastapi.responses import StreamingResponse
from pydantic_ai import DeferredToolResults, ToolApproved, ToolDenied
from pydantic_core import to_jsonable_python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, ConflictError, NotFoundError
from models.agent_run import AgentRun
from models.user import User
from models.workspace import Workspace
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL
from services.agent_runs.schemas import AgentRunResumeDecision, AgentRunResumeRequest
from services.agent_runs.utils import load_delegated_child_run_for_approval
from services.agents.delegation_approval import (
    DELEGATED_APPROVAL_CHILD_DEFERRED_TOOL_RESULTS_KEY,
)
from services.agents.runtime import streaming as runtime_streaming
from services.agents.runtime.approval_state import (
    SuspendedRunState,
    load_suspended_run_state,
)
from services.agents.runtime.events import (
    EVENT_RUN_STATUS,
    STREAM_PROTOCOL_VERSION,
    STREAM_VERSION_HEADER,
)
from services.agents.runtime.run_manager import run_task_registry
from services.agents.runtime.sinks import StreamSink
from services.agents.runtime.worker import run_resume_worker
from services.audit_events.utils import request_audit_context


async def resume_agent_run_stream(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    run_id: UUID,
    payload: AgentRunResumeRequest,
    request: Request | None = None,
) -> StreamingResponse:
    """Validate human approval decisions and stream the resumed run."""
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
    deferred_tool_results = await _build_deferred_tool_results(
        db,
        run=run,
        suspended_state=suspended_state,
        decisions=payload.decisions,
    )
    if request is not None:
        run.metadata_json = {
            **(run.metadata_json or {}),
            "audit_context": request_audit_context(request),
        }
        await db.commit()

    sink = StreamSink(run_id=run.id, conversation_id=run.conversation_id)
    await sink.emit(EVENT_RUN_STATUS, {"status": run.status})
    run_task_registry.spawn(
        run.id,
        run_resume_worker(
            run_id=run.id,
            conversation_id=run.conversation_id,
            message_history=suspended_state.message_history,
            deferred_tool_results=deferred_tool_results,
            sink=sink,
        ),
    )

    return StreamingResponse(
        runtime_streaming.drain_sse_sink(sink),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            STREAM_VERSION_HEADER: STREAM_PROTOCOL_VERSION,
            "X-Accel-Buffering": "no",
        },
    )


async def _build_deferred_tool_results(
    db: AsyncSession,
    *,
    run: AgentRun,
    suspended_state: SuspendedRunState,
    decisions: list[AgentRunResumeDecision],
) -> DeferredToolResults:
    by_id: dict[str, AgentRunResumeDecision] = {}
    duplicate_ids = []
    for decision in decisions:
        if decision.tool_call_id in by_id:
            duplicate_ids.append(decision.tool_call_id)
        by_id[decision.tool_call_id] = decision

    if duplicate_ids:
        raise AppValidationError(
            "Resume decisions contain duplicate tool_call_id values",
            field="decisions",
            details={"duplicate_tool_call_ids": duplicate_ids},
        )

    direct_pending_tool_call_ids: list[str] = []
    delegated_child_states: dict[str, tuple[dict[str, object], SuspendedRunState]] = {}

    for approval in suspended_state.deferred_tool_requests.approvals:
        metadata = suspended_state.deferred_tool_requests.metadata.get(
            approval.tool_call_id
        )
        child_run = await load_delegated_child_run_for_approval(
            db,
            parent_run=run,
            metadata=metadata,
        )
        if child_run is None:
            direct_pending_tool_call_ids.append(approval.tool_call_id)
            continue

        if not isinstance(metadata, dict):
            direct_pending_tool_call_ids.append(approval.tool_call_id)
            continue
        delegated_child_states[approval.tool_call_id] = (
            metadata,
            load_suspended_run_state(child_run),
        )

    expected = set(direct_pending_tool_call_ids)
    for _metadata, child_state in delegated_child_states.values():
        expected.update(child_state.pending_tool_call_ids)

    received = set(by_id)
    if received != expected:
        raise AppValidationError(
            "Resume decisions must cover exactly the pending approvals",
            field="decisions",
            details={
                "missing_tool_call_ids": sorted(expected - received),
                "unexpected_tool_call_ids": sorted(received - expected),
            },
        )

    approvals = {}
    metadata_by_parent_tool_call_id: dict[str, dict[str, object]] = {}
    for tool_call_id in direct_pending_tool_call_ids:
        approvals[tool_call_id] = _approval_result_for_decision(by_id[tool_call_id])

    for parent_tool_call_id, (
        parent_metadata,
        child_state,
    ) in delegated_child_states.items():
        child_results = DeferredToolResults(
            approvals={
                child_tool_call_id: _approval_result_for_decision(
                    by_id[child_tool_call_id]
                )
                for child_tool_call_id in child_state.pending_tool_call_ids
            }
        )
        approvals[parent_tool_call_id] = ToolApproved()
        metadata_by_parent_tool_call_id[parent_tool_call_id] = {
            **parent_metadata,
            DELEGATED_APPROVAL_CHILD_DEFERRED_TOOL_RESULTS_KEY: to_jsonable_python(
                child_results
            ),
        }

    return DeferredToolResults(
        approvals=approvals,
        metadata=metadata_by_parent_tool_call_id,
    )


def _approval_result_for_decision(
    decision: AgentRunResumeDecision,
) -> ToolApproved | ToolDenied:
    if decision.decision == "approved":
        return ToolApproved(override_args=decision.override_args)
    return ToolDenied(decision.message or "Denied by user")
