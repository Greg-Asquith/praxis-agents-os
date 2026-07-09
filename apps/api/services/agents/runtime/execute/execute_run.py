# apps/api/services/agents/runtime/execute/execute_run.py

"""Execute one agent turn through Pydantic AI."""

from collections.abc import Sequence
from uuid import UUID

from pydantic_ai import DeferredToolResults
from pydantic_ai.messages import ModelMessage, UserContent
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent_runs.domain import RUN_STATUS_PENDING, RUN_STATUS_RUNNING
from services.agents.runtime.events import EVENT_RUN_STATUS
from services.agents.runtime.load_context import (
    load_agent_skills,
    load_available_files,
    load_run_context,
)
from services.agents.runtime.sinks import EventSink, NullSink

from .finalize import emit_failure_events, finalize_terminal_run
from .setup import (
    RunEnvelopeBuilder,
    RuntimeAgentBuilder,
    prepare_runtime,
    start_run,
    validate_execution_preconditions,
)
from .stream import consume_stream
from .types import ExecuteRunResult


async def execute_run_with_builders(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    run_id: UUID,
    user_prompt: str | Sequence[UserContent] | None,
    attachment_file_ids: Sequence[UUID] = (),
    sink: EventSink | None = None,
    model: Model | None = None,
    client_message_id: str | None = None,
    owner_instance_id: str | None = None,
    expected_status: str | None = RUN_STATUS_PENDING,
    message_history: Sequence[ModelMessage] | None = None,
    deferred_tool_results: DeferredToolResults | None = None,
    usage: RunUsage | None = None,
    runtime_agent_builder: RuntimeAgentBuilder,
    run_envelope_builder: RunEnvelopeBuilder,
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
    skills = await load_agent_skills(db, agent)
    available_files = await load_available_files(db, conversation)
    event_sink = sink or NullSink(run_id=run.id, conversation_id=conversation.id)
    started = False

    try:
        validate_execution_preconditions(
            run,
            user_prompt=user_prompt,
            message_history=message_history,
            deferred_tool_results=deferred_tool_results,
            expected_status=expected_status,
        )

        await start_run(db, run, owner_instance_id=owner_instance_id)
        started = True
        await event_sink.emit(EVENT_RUN_STATUS, {"status": RUN_STATUS_RUNNING})

        prepared = await prepare_runtime(
            db,
            run=run,
            conversation=conversation,
            agent=agent,
            model=model,
            event_sink=event_sink,
            user_prompt=user_prompt,
            attachment_file_ids=attachment_file_ids,
            message_history=message_history,
            deferred_tool_results=deferred_tool_results,
            skills=skills,
            available_files=available_files,
            runtime_agent_builder=runtime_agent_builder,
            run_envelope_builder=run_envelope_builder,
        )
        built_agent = prepared.built_agent

        async with built_agent.runtime_agent.agent.run_stream_events(
            prepared.user_prompt,
            deps=prepared.deps,
            message_history=built_agent.history,
            deferred_tool_results=deferred_tool_results,
            conversation_id=str(conversation.id),
            usage_limits=built_agent.runtime_agent.usage_limits,
            usage=usage,
        ) as stream:
            terminal_result = await consume_stream(
                stream,
                deps=prepared.deps,
                skills=skills,
                run=run,
                deferred_tool_results=deferred_tool_results,
                event_sink=event_sink,
            )

        if terminal_result is None:
            raise RuntimeError("Pydantic AI stream ended without a terminal result")

        return await finalize_terminal_run(
            db,
            event_sink=event_sink,
            conversation=conversation,
            run=run,
            terminal_result=terminal_result,
            client_message_id=client_message_id,
            history=built_agent.history,
            deferred_tool_results=deferred_tool_results,
        )
    except Exception as exc:
        await emit_failure_events(
            db,
            event_sink=event_sink,
            started=started,
            run_id=run_id,
            exc=exc,
        )
        raise
    finally:
        await event_sink.close()
