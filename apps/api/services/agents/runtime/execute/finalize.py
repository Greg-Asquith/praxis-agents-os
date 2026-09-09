# apps/api/services/agents/runtime/execute/finalize.py

"""Persist terminal execute_run outcomes and emit terminal events."""

import logging
from collections.abc import Sequence
from contextlib import suppress
from typing import Any
from uuid import UUID

from pydantic_ai import DeferredToolRequests, DeferredToolResults
from pydantic_ai.messages import ModelMessage
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import (
    configure_async_db_session,
    get_ai_usage_async_db_session_factory,
    get_async_db_session_factory,
    set_session_tenant_context,
)
from models.agent_run import AgentRun
from models.conversation import Conversation
from services.agent_runs.domain import (
    RUN_STATUS_AWAITING_APPROVAL,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
)
from services.agent_runs.get_approval_state import get_agent_run_approval_state
from services.agents.runtime.approval_events import (
    add_approval_display_args,
    approval_events_for_projection,
    build_deferred_tool_result_metadata,
    emit_deferred_tool_resume_events,
)
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.dispatch import record_policy_approval_request_audit_events
from services.agents.runtime.execution_control import ExecutionInterruptedError, InterruptionReason
from services.agents.runtime.run_persistence import (
    persist_cancelled_run,
    persist_failed_run,
    persist_successful_run,
    persist_suspended_run,
)
from services.agents.runtime.sinks import EventSink
from services.agents.runtime.stream_protocol import DoneEvent, ErrorEvent, RunStatusEvent
from services.ai_usage.agent_run_accounting import AgentRunMeteringContext
from services.ai_usage.domain import AIUsageEventData
from services.ai_usage.record_in_transaction import record_ai_usage_in_transaction

from .errors import public_run_error
from .types import ExecuteRunResult

CANCEL_FINALIZE_TIMEOUT = 3.0
logger = logging.getLogger(__name__)


async def finalize_terminal_run(
    db: AsyncSession,
    *,
    event_sink: EventSink,
    conversation: Conversation,
    run: AgentRun,
    terminal_result: Any,
    client_message_id: str | None,
    history: Sequence[ModelMessage],
    deferred_tool_results: DeferredToolResults | None,
    deps: RuntimeDeps,
    skip_initial_user_prompt: bool = False,
    live_deferred_result_ids: Sequence[str] | set[str] = (),
    eager_tool_return_ids: set[str] | None = None,
    usage_event: AIUsageEventData | None = None,
) -> ExecuteRunResult:
    if deferred_tool_results is not None:
        await emit_deferred_tool_resume_events(
            event_sink,
            message_history=history,
            new_messages=terminal_result.new_messages(),
            deferred_tool_results=deferred_tool_results,
            already_emitted_tool_call_ids=live_deferred_result_ids,
        )

    if isinstance(terminal_result.output, DeferredToolRequests):
        return await finalize_suspended_run(
            db,
            event_sink=event_sink,
            conversation=conversation,
            run=run,
            terminal_result=terminal_result,
            client_message_id=client_message_id,
            deps=deps,
            skip_initial_user_prompt=skip_initial_user_prompt,
            eager_tool_return_ids=eager_tool_return_ids,
            usage_event=usage_event,
        )

    return await finalize_successful_run(
        db,
        event_sink=event_sink,
        conversation=conversation,
        run=run,
        terminal_result=terminal_result,
        client_message_id=client_message_id,
        history=history,
        deferred_tool_results=deferred_tool_results,
        skip_initial_user_prompt=skip_initial_user_prompt,
        eager_tool_return_ids=eager_tool_return_ids,
        usage_event=usage_event,
    )


async def finalize_suspended_run(
    db: AsyncSession,
    *,
    event_sink: EventSink,
    conversation: Conversation,
    run: AgentRun,
    terminal_result: Any,
    client_message_id: str | None,
    deps: RuntimeDeps,
    skip_initial_user_prompt: bool = False,
    eager_tool_return_ids: set[str] | None = None,
    usage_event: AIUsageEventData | None = None,
) -> ExecuteRunResult:
    deferred_tool_requests = terminal_result.output
    deferred_tool_requests = await add_approval_display_args(deps, deferred_tool_requests)
    await record_policy_approval_request_audit_events(
        deps=deps,
        deferred_tool_requests=deferred_tool_requests,
    )
    suspended_run, new_message_count, deferred_tool_requests = await persist_suspended_run(
        db,
        conversation_id=conversation.id,
        run_id=run.id,
        terminal_result=terminal_result,
        deferred_tool_requests=deferred_tool_requests,
        client_message_id=client_message_id,
        skip_initial_user_prompt=skip_initial_user_prompt,
        eager_tool_return_ids=eager_tool_return_ids,
        usage_event=usage_event,
    )
    if suspended_run.status == RUN_STATUS_AWAITING_APPROVAL and deferred_tool_requests is not None:
        if suspended_run.parent_run_id is None:
            projection = await get_agent_run_approval_state(
                db, actor=deps.user, workspace=deps.workspace, run_id=suspended_run.id
            )
            for event in approval_events_for_projection(projection):
                await event_sink.emit(event)
    else:
        deferred_tool_requests = None
    await emit_final_events(event_sink, suspended_run)
    return ExecuteRunResult(
        run=suspended_run,
        output=deferred_tool_requests,
        new_message_count=new_message_count,
    )


async def finalize_successful_run(
    db: AsyncSession,
    *,
    event_sink: EventSink,
    conversation: Conversation,
    run: AgentRun,
    terminal_result: Any,
    client_message_id: str | None,
    history: Sequence[ModelMessage],
    deferred_tool_results: DeferredToolResults | None,
    skip_initial_user_prompt: bool = False,
    eager_tool_return_ids: set[str] | None = None,
    usage_event: AIUsageEventData | None = None,
) -> ExecuteRunResult:
    tool_approval_metadata_by_call_id = (
        build_deferred_tool_result_metadata(
            message_history=history,
            new_messages=terminal_result.new_messages(),
            deferred_tool_results=deferred_tool_results,
        )
        if deferred_tool_results is not None
        else None
    )

    final_run, new_message_count = await persist_successful_run(
        db,
        conversation_id=conversation.id,
        run_id=run.id,
        terminal_result=terminal_result,
        client_message_id=client_message_id,
        tool_approval_metadata_by_call_id=tool_approval_metadata_by_call_id,
        skip_initial_user_prompt=skip_initial_user_prompt,
        eager_tool_return_ids=eager_tool_return_ids,
        usage_event=usage_event,
    )
    await emit_final_events(event_sink, final_run)

    return ExecuteRunResult(
        run=final_run,
        output=(
            terminal_result.output
            if final_run.status == RUN_STATUS_COMPLETED
            and (
                usage_event is None
                or final_run.owner_instance_id is None
                or final_run.owner_instance_id == (usage_event.details or {}).get("invocation_id")
            )
            else None
        ),
        new_message_count=new_message_count,
    )


async def emit_failure_events(
    db: AsyncSession,
    *,
    event_sink: EventSink,
    started: bool,
    run_id: UUID,
    exc: Exception,
    metering: AgentRunMeteringContext | None = None,
    owner_instance_id: str | None = None,
) -> AgentRun | None:
    public_error = public_run_error(exc)
    logger.error(
        "Agent run execution failed",
        exc_info=(type(exc), exc, exc.__traceback__),
        extra={
            "agent_run_id": str(run_id),
            "run_started": started,
            "public_error_code": public_error.code,
        },
    )
    await db.rollback()
    if started:
        failed_run = await persist_failed_run(
            db,
            run_id=run_id,
            error_code=public_error.code,
            error_message=public_error.message,
            completion_json=public_error.completion_json,
            metering=metering,
            owner_instance_id=owner_instance_id,
        )
        if failed_run is not None:
            await emit_final_events(event_sink, failed_run)
            return failed_run
    else:
        await event_sink.emit(
            ErrorEvent(code=public_error.code, message=public_error.message),
        )
    await event_sink.emit(DoneEvent(status=RUN_STATUS_FAILED))
    return None


async def finalize_cancelled_run(
    *,
    event_sink: EventSink,
    run_id: UUID,
    workspace_id: UUID,
    user_id: UUID,
    metering: AgentRunMeteringContext | None = None,
    owner_instance_id: str | None = None,
) -> None:
    """Settles cancellation using an isolated persistence session."""
    cancelled_run = await persist_cancelled_run(
        run_id,
        workspace_id=workspace_id,
        user_id=user_id,
        metering=metering,
        owner_instance_id=owner_instance_id,
    )
    if cancelled_run is None:
        raise RuntimeError("Cancellation settlement did not complete")
    with suppress(Exception):
        await emit_final_events(event_sink, cancelled_run)


async def emit_final_events(event_sink: EventSink, run: AgentRun) -> None:
    """Projects final events from the committed run verdict."""
    await event_sink.emit(RunStatusEvent(status=run.status))
    if run.status == RUN_STATUS_FAILED:
        await event_sink.emit(
            ErrorEvent(
                code=run.error_code or RUN_STATUS_FAILED,
                message=run.error_message or "Agent run failed",
            )
        )
    await event_sink.emit(DoneEvent(status=run.status))


async def finalize_interrupted_usage(event: AIUsageEventData) -> None:
    """Settles shutdown usage without changing the run's lifecycle verdict."""
    async with get_ai_usage_async_db_session_factory()() as db:
        await configure_async_db_session(db)
        await set_session_tenant_context(db, workspace_id=event.workspace_id, user_id=event.user_id)
        await record_ai_usage_in_transaction(db, event)
        await db.commit()


async def finalize_stopped_run(
    *,
    event_sink: EventSink,
    run_id: UUID,
    workspace_id: UUID,
    user_id: UUID,
    reason: InterruptionReason,
    owner_instance_id: str | None,
    metering: AgentRunMeteringContext | None = None,
) -> None:
    """Settles an interrupted invocation in its own tenant session."""
    error = public_run_error(ExecutionInterruptedError(reason))
    async with get_async_db_session_factory()() as db:
        await configure_async_db_session(db)
        await set_session_tenant_context(db, workspace_id=workspace_id, user_id=user_id)
        run = await persist_failed_run(
            db,
            run_id=run_id,
            error_code=error.code,
            error_message=error.message,
            metering=metering,
            owner_instance_id=owner_instance_id,
        )
        if run is not None:
            await emit_final_events(event_sink, run)
