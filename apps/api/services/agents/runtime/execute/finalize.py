# apps/api/services/agents/runtime/execute/finalize.py

"""Persist terminal execute_run outcomes and emit terminal events."""

from collections.abc import Sequence
from contextlib import suppress
from typing import Any
from uuid import UUID

from pydantic_ai import DeferredToolRequests, DeferredToolResults
from pydantic_ai.messages import ModelMessage
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_run import AgentRun
from models.conversation import Conversation
from services.agent_runs.domain import (
    RUN_STATUS_AWAITING_APPROVAL,
    RUN_STATUS_CANCELLED,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
)
from services.agents.runtime.approval_events import (
    build_deferred_tool_result_metadata,
    emit_approval_required_events,
    emit_deferred_tool_resume_events,
)
from services.agents.runtime.events import EVENT_DONE, EVENT_ERROR, EVENT_RUN_STATUS
from services.agents.runtime.run_persistence import (
    persist_cancelled_run,
    persist_failed_run,
    persist_successful_run,
    persist_suspended_run,
)
from services.agents.runtime.sinks import EventSink

from .types import ExecuteRunResult

CANCEL_FINALIZE_TIMEOUT = 3.0


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
    skip_initial_user_prompt: bool = False,
) -> ExecuteRunResult:
    if deferred_tool_results is not None:
        await emit_deferred_tool_resume_events(
            event_sink,
            message_history=history,
            new_messages=terminal_result.new_messages(),
            deferred_tool_results=deferred_tool_results,
        )

    if isinstance(terminal_result.output, DeferredToolRequests):
        return await finalize_suspended_run(
            db,
            event_sink=event_sink,
            conversation=conversation,
            run=run,
            terminal_result=terminal_result,
            client_message_id=client_message_id,
            skip_initial_user_prompt=skip_initial_user_prompt,
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
    )


async def finalize_suspended_run(
    db: AsyncSession,
    *,
    event_sink: EventSink,
    conversation: Conversation,
    run: AgentRun,
    terminal_result: Any,
    client_message_id: str | None,
    skip_initial_user_prompt: bool = False,
) -> ExecuteRunResult:
    deferred_tool_requests = terminal_result.output
    suspended_run, new_message_count, deferred_tool_requests = await persist_suspended_run(
        db,
        conversation_id=conversation.id,
        run_id=run.id,
        terminal_result=terminal_result,
        deferred_tool_requests=deferred_tool_requests,
        client_message_id=client_message_id,
        skip_initial_user_prompt=skip_initial_user_prompt,
    )
    await emit_approval_required_events(event_sink, deferred_tool_requests)
    await event_sink.emit(
        EVENT_RUN_STATUS,
        {"status": RUN_STATUS_AWAITING_APPROVAL},
    )
    await event_sink.emit(EVENT_DONE, {"status": RUN_STATUS_AWAITING_APPROVAL})
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
    )
    if final_run.status == RUN_STATUS_COMPLETED:
        await event_sink.emit(EVENT_RUN_STATUS, {"status": RUN_STATUS_COMPLETED})
        await event_sink.emit(EVENT_DONE, {"status": RUN_STATUS_COMPLETED})
    else:
        await event_sink.emit(EVENT_RUN_STATUS, {"status": final_run.status})
        if final_run.status == RUN_STATUS_FAILED:
            await event_sink.emit(
                EVENT_ERROR,
                {
                    "code": final_run.error_code or RUN_STATUS_FAILED,
                    "message": final_run.error_message or "Agent run failed",
                },
            )
        await event_sink.emit(EVENT_DONE, {"status": final_run.status})

    return ExecuteRunResult(
        run=final_run,
        output=terminal_result.output,
        new_message_count=new_message_count,
    )


async def emit_failure_events(
    db: AsyncSession,
    *,
    event_sink: EventSink,
    started: bool,
    run_id: UUID,
    exc: Exception,
) -> None:
    await db.rollback()
    terminal_status = RUN_STATUS_FAILED
    if started:
        failed_run = await persist_failed_run(
            db,
            run_id=run_id,
            error_code=exc.__class__.__name__,
            error_message=str(exc),
        )
        if failed_run is not None:
            terminal_status = failed_run.status
            await event_sink.emit(EVENT_RUN_STATUS, {"status": failed_run.status})
            if failed_run.status == RUN_STATUS_FAILED:
                await event_sink.emit(
                    EVENT_ERROR,
                    {
                        "code": failed_run.error_code or exc.__class__.__name__,
                        "message": failed_run.error_message or str(exc),
                    },
                )
    else:
        await event_sink.emit(
            EVENT_ERROR,
            {
                "code": exc.__class__.__name__,
                "message": str(exc),
            },
        )
    await event_sink.emit(EVENT_DONE, {"status": terminal_status})


async def finalize_cancelled_run(
    db: AsyncSession,
    *,
    event_sink: EventSink,
    run_id: UUID,
) -> None:
    """Persist and emit cancelled terminal state during cancellation unwind."""
    with suppress(Exception):
        await db.rollback()

    status = RUN_STATUS_CANCELLED
    with suppress(Exception):
        cancelled_run = await persist_cancelled_run(run_id)
        if cancelled_run is not None:
            status = str(cancelled_run.status)

    with suppress(BaseException):
        await event_sink.emit(EVENT_RUN_STATUS, {"status": status})
        await event_sink.emit(EVENT_DONE, {"status": status})
