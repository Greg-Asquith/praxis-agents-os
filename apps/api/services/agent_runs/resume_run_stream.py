# apps/api/services/agent_runs/resume_run_stream.py

"""Resume a suspended agent run and stream the continuation."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError, NotFoundError
from models.agent_run import AgentRun
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.agent_runs.continuation_state import (
    CONTINUATION_KEY,
    load_approval_continuation,
    resume_request_digest,
)
from services.agent_runs.domain import RUN_STATUS_AWAITING_APPROVAL, RUN_STATUS_RUNNING
from services.agent_runs.require_root_approval import require_root_approval
from services.agent_runs.schemas import AgentRunResumeRequest
from services.agent_runs.settle_run_family import lock_run_family, settle_run_family
from services.agents.runtime import streaming as runtime_streaming
from services.agents.runtime.events import (
    STREAM_PROTOCOL_VERSION,
    STREAM_VERSION_HEADER,
)
from services.agents.runtime.execution_control import execution_control_for_run
from services.agents.runtime.run_manager import run_task_registry
from services.agents.runtime.sinks import StreamSink
from services.agents.runtime.stream_protocol import RunStatusEvent
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
    from services.agent_runs.compile_approval_decisions import compile_approval_decisions
    from services.agent_runs.load_approval_graph import load_approval_graph
    from services.agent_runs.reserve_approval_continuation import reserve_approval_continuation
    from services.agents.runtime.approval_projection import project_approval_graph

    run = await db.scalar(
        select(AgentRun)
        .where(
            AgentRun.id == run_id,
            AgentRun.workspace_id == workspace.id,
            AgentRun.user_id == actor.id,
            AgentRun.deleted == False,  # noqa: E712
        )
        .execution_options(populate_existing=True)
    )
    if run is None:
        raise NotFoundError(
            "Agent run not found",
            resource_type="agent_run",
            resource_id=str(run_id),
        )
    await require_root_approval(db, run=run, actor=actor, workspace=workspace)
    family = await lock_run_family(db, run_id=run_id)
    if not family:
        raise ConflictError("Parent run is no longer active", conflicting_resource="agent_run")
    if CONTINUATION_KEY in (run.metadata_json or {}):
        reservation = load_approval_continuation(run)
        identical = reservation.request_digest == resume_request_digest(payload)
        raise ConflictError(
            "This approval has already been reserved. Refresh the conversation.",
            conflicting_resource="agent_run",
            details={
                "code": "approval_already_reserved" if identical else "approval_decisions_conflict",
                "root_run_id": str(run.id),
                "root_conversation_id": str(run.conversation_id),
                "decisions_accepted": identical,
            },
        )
    if run.status != RUN_STATUS_AWAITING_APPROVAL:
        raise ConflictError(
            "Agent run is not awaiting approval",
            conflicting_resource="agent_run",
            details={"run_id": str(run.id), "run_status": run.status},
        )

    membership = await db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace.id,
            WorkspaceMembership.user_id == actor.id,
        )
    )
    if membership is None:
        raise NotFoundError("Workspace membership not found", resource_type="workspace_membership")
    from services.agent_runs.approval_expiry import approval_family_deadline

    deadline = approval_family_deadline(family)
    if deadline is not None and deadline <= datetime.now(UTC):
        await settle_run_family(
            db,
            run_id=run.id,
            error_code="approval_expired",
            error_message="These approvals expired before they were accepted.",
        )
        await db.commit()
        raise ConflictError(
            "These approvals have expired. Refresh the conversation.",
            conflicting_resource="agent_run",
            details={"code": "approval_expired"},
        )
    try:
        graph = await load_approval_graph(db, actor=actor, workspace=workspace, run_id=run.id)
        projection = project_approval_graph(graph)
    except ConflictError as exc:
        if str(exc) != "Saved workflow state is invalid" and not str(exc).startswith(
            "Delegated approval child is "
        ):
            raise
        await settle_run_family(
            db,
            run_id=run.id,
            error_code="agent_run_resume_requires_recovery",
            error_message="Review the previous actions before continuing this conversation.",
        )
        await db.commit()
        raise ConflictError(
            "The saved approvals need review before this conversation can continue.",
            conflicting_resource="agent_run",
            details={"code": "agent_run_resume_requires_recovery", "root_run_id": str(run.id)},
        ) from exc
    runs = {member.id: member for member in family}
    deferred_tool_results = await compile_approval_decisions(
        db,
        actor=actor,
        workspace=workspace,
        membership=membership,
        graph=graph,
        runs=runs,
        payload=payload,
    )
    reservation = await reserve_approval_continuation(
        db,
        run=run,
        graph=graph,
        runs=runs,
        payload=payload,
        revision=projection.approval_revision,
        results=deferred_tool_results,
    )
    if request is not None:
        run.metadata_json = {
            **(run.metadata_json or {}),
            "audit_context": request_audit_context(request),
        }
    owner_instance_id = str(reservation.owner_instance_id)
    await db.commit()

    execution_control = execution_control_for_run(run)
    sink = StreamSink(run_id=run.id, conversation_id=run.conversation_id)
    await sink.emit(RunStatusEvent(status=run.status))
    from services.agents.runtime.worker import run_resume_worker

    run_task_registry.spawn(
        run.id,
        run_resume_worker(
            owner_instance_id=owner_instance_id,
            execution_control=execution_control,
            run_id=run.id,
            conversation_id=run.conversation_id,
            workspace_id=workspace.id,
            user_id=actor.id,
            sink=sink,
            expected_status=RUN_STATUS_RUNNING,
        ),
        sink=sink,
        execution_control=execution_control,
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
