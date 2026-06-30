# apps/api/services/agents/runtime/execute_run.py

"""Execute one agent turn through Pydantic AI."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic_ai import DeferredToolRequests, DeferredToolResults
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models import Model
from pydantic_ai.run import AgentRunResultEvent
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError
from models.agent_run import AgentRun
from services.agent_runs.domain import (
    RUN_STATUS_AWAITING_APPROVAL,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_PENDING,
    RUN_STATUS_RUNNING,
)
from services.agent_runs.start_with_lease import start_agent_run_with_lease
from services.agents.runtime.approval_events import (
    emit_approval_required_events,
    emit_deferred_tool_resume_events,
    is_deferred_tool_resume_event,
)
from services.agents.runtime.context import RuntimeDeps
from services.agents.runtime.events import (
    EVENT_DONE,
    EVENT_ERROR,
    EVENT_RUN_STATUS,
    EventTranslationState,
    emit_agent_stream_event,
)
from services.agents.runtime.load_context import load_actor_context, load_run_context
from services.agents.runtime.loop import build_runtime_agent
from services.agents.runtime.persistence import load_message_history
from services.agents.runtime.run_persistence import (
    persist_failed_run,
    persist_successful_run,
    persist_suspended_run,
)
from services.agents.runtime.sinks import EventSink, NullSink


@dataclass(frozen=True)
class ExecuteRunResult:
    """Result returned by the Praxis runtime core."""

    run: AgentRun
    output: Any
    new_message_count: int


async def execute_run(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    run_id: UUID,
    user_prompt: str | None,
    sink: EventSink | None = None,
    model: Model | None = None,
    client_message_id: str | None = None,
    owner_instance_id: str | None = None,
    expected_status: str | None = RUN_STATUS_PENDING,
    message_history: Sequence[ModelMessage] | None = None,
    deferred_tool_results: DeferredToolResults | None = None,
) -> ExecuteRunResult:
    """Drive one agent turn to completion or approval suspension.

    The user prompt is persisted from Pydantic AI's ``new_messages()``; callers
    must not insert a separate user message for the same turn. Resume callers
    pass rehydrated ``message_history`` and ``deferred_tool_results`` instead of a
    new prompt. This function owns the run lifecycle transaction boundaries: it
    commits the running+lease state before provider streaming, commits final
    messages/usage/status after the stream, and commits failures before
    re-raising so rollback-based dependencies do not erase diagnostic state.
    """
    run, conversation, agent = await load_run_context(
        db,
        conversation_id=conversation_id,
        run_id=run_id,
        lock_run=True,
    )
    event_sink = sink or NullSink(run_id=run.id, conversation_id=conversation.id)
    started = False

    try:
        if expected_status is not None and run.status != expected_status:
            raise ConflictError(
                "Agent run is not in the expected state for execution",
                conflicting_resource="agent_run",
                details={
                    "run_id": str(run.id),
                    "run_status": run.status,
                    "expected_status": expected_status,
                },
            )
        if user_prompt is None and deferred_tool_results is None:
            raise ConflictError(
                "Agent run needs a prompt or deferred tool results",
                conflicting_resource="agent_run",
                details={"run_id": str(run.id)},
            )
        if deferred_tool_results is not None and message_history is None:
            raise ConflictError(
                "Agent run resume needs rehydrated message history",
                conflicting_resource="agent_run",
                details={"run_id": str(run.id)},
            )

        await start_agent_run_with_lease(
            db,
            run,
            owner_instance_id=owner_instance_id,
        )
        await db.commit()
        started = True
        await event_sink.emit(EVENT_RUN_STATUS, {"status": RUN_STATUS_RUNNING})

        runtime_agent = build_runtime_agent(agent, model=model)
        if run.model_name is None:
            run.model_name = runtime_agent.resolved_model.qualified_id

        history = (
            list(message_history)
            if message_history is not None
            else await load_message_history(db, conversation_id=conversation.id)
        )
        user, workspace = await load_actor_context(db, run)
        await db.commit()
        deps = RuntimeDeps(
            db=db,
            user=user,
            workspace=workspace,
            conversation=conversation,
            agent=agent,
            run=run,
            sink=event_sink,
        )
        state = EventTranslationState()
        terminal_result = None
        deferred_tool_call_ids = (
            set(deferred_tool_results.approvals)
            if deferred_tool_results is not None
            else set()
        )

        async with runtime_agent.agent.run_stream_events(
            user_prompt,
            deps=deps,
            message_history=history,
            deferred_tool_results=deferred_tool_results,
            conversation_id=str(conversation.id),
            usage_limits=runtime_agent.usage_limits,
        ) as stream:
            async for event in stream:
                if isinstance(event, AgentRunResultEvent):
                    terminal_result = event.result
                    continue
                if (
                    deferred_tool_results is not None
                    and is_deferred_tool_resume_event(
                        event,
                        deferred_tool_call_ids=deferred_tool_call_ids,
                    )
                ):
                    continue
                await emit_agent_stream_event(
                    event_sink,
                    event,
                    run_id=str(run.id),
                    state=state,
                )

        if terminal_result is None:
            raise RuntimeError("Pydantic AI stream ended without a terminal result")

        if deferred_tool_results is not None:
            await emit_deferred_tool_resume_events(
                event_sink,
                message_history=history,
                new_messages=terminal_result.new_messages(),
                deferred_tool_results=deferred_tool_results,
            )

        if isinstance(terminal_result.output, DeferredToolRequests):
            suspended_run, new_message_count = await persist_suspended_run(
                db,
                conversation_id=conversation.id,
                run_id=run.id,
                terminal_result=terminal_result,
                deferred_tool_requests=terminal_result.output,
                client_message_id=client_message_id,
            )
            await emit_approval_required_events(event_sink, terminal_result.output)
            await event_sink.emit(
                EVENT_RUN_STATUS,
                {"status": RUN_STATUS_AWAITING_APPROVAL},
            )
            await event_sink.emit(EVENT_DONE, {"status": RUN_STATUS_AWAITING_APPROVAL})
            return ExecuteRunResult(
                run=suspended_run,
                output=terminal_result.output,
                new_message_count=new_message_count,
            )

        final_run, new_message_count = await persist_successful_run(
            db,
            conversation_id=conversation.id,
            run_id=run.id,
            terminal_result=terminal_result,
            client_message_id=client_message_id,
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
    except Exception as exc:
        await db.rollback()
        terminal_status = RUN_STATUS_FAILED
        if started:
            failed_run = await persist_failed_run(
                db,
                run_id=run.id,
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
        raise
    finally:
        await event_sink.close()
