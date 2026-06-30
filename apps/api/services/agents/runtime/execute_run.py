# apps/api/services/agents/runtime/execute_run.py

"""Execute one agent turn through Pydantic AI."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic_ai.models import Model
from pydantic_ai.run import AgentRunResultEvent
from pydantic_core import to_jsonable_python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions.general import ConflictError, NotFoundError
from models.agent import Agent
from models.agent_run import AgentRun
from models.conversation import Conversation
from services.agent_runs import (
    complete_agent_run,
    fail_agent_run,
    record_run_usage,
    start_agent_run_with_lease,
)
from services.agent_runs.domain import (
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_RUNNING,
    RunUsageSnapshot,
    is_terminal,
)
from services.agents.runtime.events import (
    EVENT_DONE,
    EVENT_ERROR,
    EVENT_RUN_STATUS,
    EventTranslationState,
    emit_agent_stream_event,
)
from services.agents.runtime.loop import RuntimeDeps, build_runtime_agent
from services.agents.runtime.persistence import load_message_history, persist_new_messages
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
    user_prompt: str,
    sink: EventSink | None = None,
    model: Model | None = None,
    client_message_id: str | None = None,
    owner_instance_id: str | None = None,
) -> ExecuteRunResult:
    """Drive one agent turn to completion and persist its durable side effects.

    The user prompt is persisted from Pydantic AI's ``new_messages()``; callers
    must not insert a separate user message for the same turn. This function owns
    the run lifecycle transaction boundaries: it commits the running+lease state
    before provider streaming, commits final messages/usage/status after the
    stream, and commits failures before re-raising so rollback-based dependencies
    do not erase diagnostic state.
    """
    run, conversation, agent = await _load_run_context(
        db,
        conversation_id=conversation_id,
        run_id=run_id,
    )
    event_sink = sink or NullSink(run_id=run.id, conversation_id=conversation.id)
    started = False

    try:
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

        history = await load_message_history(db, conversation_id=conversation.id)
        await db.commit()
        deps = RuntimeDeps(
            db=db,
            conversation=conversation,
            agent=agent,
            run=run,
            sink=event_sink,
        )
        state = EventTranslationState()
        terminal_result = None

        async with runtime_agent.agent.run_stream_events(
            user_prompt,
            deps=deps,
            message_history=history,
            conversation_id=str(conversation.id),
            usage_limits=runtime_agent.usage_limits,
        ) as stream:
            async for event in stream:
                if isinstance(event, AgentRunResultEvent):
                    terminal_result = event.result
                    continue
                await emit_agent_stream_event(
                    event_sink,
                    event,
                    run_id=str(run.id),
                    state=state,
                )

        if terminal_result is None:
            raise RuntimeError("Pydantic AI stream ended without a terminal result")

        final_run, new_message_count = await _persist_successful_run(
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
        if started:
            failed_run = await _persist_failed_run(
                db,
                run_id=run.id,
                error_code=exc.__class__.__name__,
                error_message=str(exc),
            )
            if failed_run is not None and failed_run.status == RUN_STATUS_FAILED:
                await event_sink.emit(EVENT_RUN_STATUS, {"status": RUN_STATUS_FAILED})
                await event_sink.emit(
                    EVENT_ERROR,
                    {
                        "code": failed_run.error_code or exc.__class__.__name__,
                        "message": failed_run.error_message or str(exc),
                    },
                )
        raise
    finally:
        await event_sink.close()


async def _persist_successful_run(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    run_id: UUID,
    terminal_result: Any,
    client_message_id: str | None,
) -> tuple[AgentRun, int]:
    run, conversation, _agent = await _load_run_context(
        db,
        conversation_id=conversation_id,
        run_id=run_id,
        populate_existing=True,
    )
    if is_terminal(run.status):
        await db.commit()
        return run, 0
    if run.status != RUN_STATUS_RUNNING:
        raise ConflictError(
            "Agent run is no longer running",
            conflicting_resource="agent_run",
            details={"run_id": str(run.id), "status": run.status},
        )

    persisted_messages = await persist_new_messages(
        db,
        conversation=conversation,
        run_id=run.id,
        messages=terminal_result.new_messages(),
        client_message_id=client_message_id,
    )
    await record_run_usage(db, run, _usage_snapshot(terminal_result.usage))
    await complete_agent_run(db, run)
    await db.commit()
    return run, len(persisted_messages)


async def _persist_failed_run(
    db: AsyncSession,
    *,
    run_id: UUID,
    error_code: str,
    error_message: str,
) -> AgentRun | None:
    run = await db.get(AgentRun, run_id, populate_existing=True)
    if run is None:
        await db.commit()
        return None
    if is_terminal(run.status):
        await db.commit()
        return run

    await fail_agent_run(
        db,
        run,
        error_code=error_code,
        error_message=error_message,
    )
    await db.commit()
    return run


async def _load_run_context(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    run_id: UUID,
    populate_existing: bool = False,
) -> tuple[AgentRun, Conversation, Agent]:
    run_stmt = select(AgentRun).where(
        AgentRun.id == run_id,
        AgentRun.deleted == False,  # noqa: E712
    )
    if populate_existing:
        run_stmt = run_stmt.execution_options(populate_existing=True)
    run = await db.scalar(run_stmt)
    if run is None:
        raise NotFoundError(
            "Agent run not found",
            resource_type="agent_run",
            resource_id=str(run_id),
        )
    if run.conversation_id != conversation_id:
        raise ConflictError(
            "Agent run does not belong to this conversation",
            conflicting_resource="agent_run",
            details={
                "run_id": str(run.id),
                "run_conversation_id": str(run.conversation_id),
                "requested_conversation_id": str(conversation_id),
            },
        )

    conversation_stmt = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.deleted == False,  # noqa: E712
    )
    if populate_existing:
        conversation_stmt = conversation_stmt.execution_options(populate_existing=True)
    conversation = await db.scalar(conversation_stmt)
    if conversation is None:
        raise NotFoundError(
            "Conversation not found",
            resource_type="conversation",
            resource_id=str(conversation_id),
        )

    agent_stmt = select(Agent).where(
        Agent.id == run.agent_id,
        Agent.deleted == False,  # noqa: E712
    )
    if populate_existing:
        agent_stmt = agent_stmt.execution_options(populate_existing=True)
    agent = await db.scalar(agent_stmt)
    if agent is None:
        raise NotFoundError(
            "Agent not found",
            resource_type="agent",
            resource_id=str(run.agent_id),
        )

    return run, conversation, agent


def _usage_snapshot(usage) -> RunUsageSnapshot:
    raw = to_jsonable_python(usage)
    return RunUsageSnapshot(
        input_tokens=getattr(usage, "input_tokens", None),
        input_tokens_cached=getattr(usage, "cache_read_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
        requests=getattr(usage, "requests", None),
        tool_calls=getattr(usage, "tool_calls", None),
        raw_json=raw if isinstance(raw, dict) else {"usage": raw},
    )
