# apps/api/services/agent_runs/resume_run_stream.py

"""Resume a suspended agent run and stream the continuation."""

from uuid import UUID

from fastapi.responses import StreamingResponse
from pydantic_ai import DeferredToolResults, ToolApproved, ToolDenied
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import AppValidationError, ConflictError, NotFoundError
from models.agent_run import AgentRun
from models.user import User
from models.workspace import Workspace
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL
from services.agent_runs.schemas import AgentRunResumeDecision, AgentRunResumeRequest
from services.agents.runtime import streaming as runtime_streaming
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.events import (
    EVENT_RUN_STATUS,
    STREAM_PROTOCOL_VERSION,
    STREAM_VERSION_HEADER,
)
from services.agents.runtime.run_manager import run_task_registry
from services.agents.runtime.sinks import StreamSink
from services.agents.runtime.worker import run_resume_worker


async def resume_agent_run_stream(
    db: AsyncSession,
    *,
    actor: User,
    workspace: Workspace,
    run_id: UUID,
    payload: AgentRunResumeRequest,
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
    deferred_tool_results = _build_deferred_tool_results(
        pending_tool_call_ids=suspended_state.pending_tool_call_ids,
        decisions=payload.decisions,
    )

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


def _build_deferred_tool_results(
    *,
    pending_tool_call_ids: list[str],
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

    expected = set(pending_tool_call_ids)
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
    for tool_call_id in pending_tool_call_ids:
        decision = by_id[tool_call_id]
        if decision.decision == "approved":
            approvals[tool_call_id] = ToolApproved(override_args=decision.override_args)
        else:
            approvals[tool_call_id] = ToolDenied(
                decision.message or "Denied by user"
            )

    return DeferredToolResults(approvals=approvals)
