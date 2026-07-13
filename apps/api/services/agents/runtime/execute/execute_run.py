# apps/api/services/agents/runtime/execute/execute_run.py

"""Execute one agent turn through Pydantic AI."""

import asyncio
from collections.abc import Sequence
from contextlib import suppress
from uuid import UUID

from pydantic_ai import Agent as PydanticAgent, DeferredToolResults
from pydantic_ai.messages import ModelMessage, UserContent
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent_runs.domain import (
    RUN_STATUS_PENDING,
    RUN_STATUS_RUNNING,
    RUN_TRIGGER_INTERACTIVE,
)
from services.agents.runtime.cancellation import (
    clear_agent_run_cancel_request,
    is_agent_run_cancel_request,
)
from services.agents.runtime.events import EVENT_RUN_STATUS
from services.agents.runtime.load_context import (
    load_actor_context,
    load_agent_skills,
    load_available_files,
    load_run_context,
)
from services.agents.runtime.persistence import load_message_history, persist_eager_user_prompt
from services.agents.runtime.sinks import EventSink, NullSink

from .finalize import (
    CANCEL_FINALIZE_TIMEOUT,
    emit_failure_events,
    finalize_cancelled_run,
    finalize_terminal_run,
)
from .setup import (
    RunEnvelopeBuilder,
    RuntimeAgentBuilder,
    assemble_user_prompt,
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

    New turn prompts are persisted before provider streaming so cancellation does
    not lose the user message. Resume callers pass rehydrated
    ``message_history`` and ``deferred_tool_results`` instead of a new prompt.
    This function owns the run lifecycle transaction boundaries: it commits the
    running+lease state before provider streaming, commits final
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
        prepared_user_prompt = user_prompt
        attachment_file_ids_for_prepare = attachment_file_ids
        runtime_message_history = message_history
        eager_message_count = 0
        user_prompt_persisted = False
        if user_prompt is not None and run.trigger == RUN_TRIGGER_INTERACTIVE:
            if runtime_message_history is None:
                runtime_message_history = await load_message_history(
                    db,
                    conversation_id=conversation.id,
                )
            if attachment_file_ids:
                _user, workspace = await load_actor_context(db, run)
                prepared_user_prompt = await assemble_user_prompt(
                    db,
                    workspace=workspace,
                    agent=agent,
                    user_prompt=user_prompt,
                    attachment_file_ids=attachment_file_ids,
                )
                attachment_file_ids_for_prepare = ()
            eager_rows = await persist_eager_user_prompt(
                db,
                conversation=conversation,
                run_id=run.id,
                user_prompt=prepared_user_prompt,
                client_message_id=client_message_id,
            )
            await db.commit()
            eager_message_count = len(eager_rows)
            user_prompt_persisted = True
        await event_sink.emit(EVENT_RUN_STATUS, {"status": RUN_STATUS_RUNNING})

        prepared = await prepare_runtime(
            db,
            run=run,
            conversation=conversation,
            agent=agent,
            model=model,
            event_sink=event_sink,
            user_prompt=prepared_user_prompt,
            attachment_file_ids=attachment_file_ids_for_prepare,
            message_history=runtime_message_history,
            deferred_tool_results=deferred_tool_results,
            skills=skills,
            available_files=available_files,
            runtime_agent_builder=runtime_agent_builder,
            run_envelope_builder=run_envelope_builder,
        )
        built_agent = prepared.built_agent

        # Tool calls share the run-scoped AsyncSession, which forbids concurrent use, so parallel tool calls from one model response run one at a time.
        with PydanticAgent.parallel_tool_call_execution_mode("sequential"):
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

        result = await finalize_terminal_run(
            db,
            event_sink=event_sink,
            conversation=conversation,
            run=run,
            terminal_result=terminal_result,
            client_message_id=client_message_id,
            history=built_agent.history,
            deferred_tool_results=deferred_tool_results,
            skip_initial_user_prompt=user_prompt_persisted,
        )
        if eager_message_count == 0:
            return result
        return ExecuteRunResult(
            run=result.run,
            output=result.output,
            new_message_count=result.new_message_count + eager_message_count,
        )
    except asyncio.CancelledError as exc:
        if not is_agent_run_cancel_request(exc, run_id=run_id):
            with suppress(Exception):
                await db.rollback()
            raise
        finalize = asyncio.ensure_future(
            finalize_cancelled_run(
                db,
                event_sink=event_sink,
                run_id=run_id,
            )
        )
        try:
            await asyncio.shield(finalize)
        except asyncio.CancelledError:
            with suppress(BaseException):
                async with asyncio.timeout(CANCEL_FINALIZE_TIMEOUT):
                    await finalize
        raise
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
        clear_agent_run_cancel_request(run_id)
        await event_sink.close()
