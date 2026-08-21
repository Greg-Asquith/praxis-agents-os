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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent_runs.domain import (
    RUN_STATUS_COMPLETED,
    RUN_STATUS_PENDING,
    RUN_STATUS_RUNNING,
    RUN_TRIGGER_INTERACTIVE,
)
from services.agents.runtime.cancellation import (
    clear_agent_run_cancel_request,
    is_agent_run_cancel_request,
)
from services.agents.runtime.load_context import (
    load_actor_context,
    load_agent_skills,
    load_available_files,
    load_run_context,
)
from services.agents.runtime.persistence import (
    load_message_history,
    persist_eager_denied_tool_results,
    persist_eager_user_prompt,
)
from services.agents.runtime.sinks import EventSink, NullSink
from services.agents.runtime.stream_protocol import RunStatusEvent
from services.ai_usage.agent_run_accounting import AgentRunMeteringContext
from services.ai_usage.domain import PURPOSE_AGENT_RUN, AIUsageEventData
from services.ai_usage.utils import sum_response_usage, usage_values
from services.conversation_summaries.safe_enqueue_history_summary import (
    safe_enqueue_history_summary,
)

from .finalize import (
    CANCEL_FINALIZE_TIMEOUT,
    emit_failure_events,
    finalize_cancelled_run,
    finalize_terminal_run,
)
from .setup import (
    assemble_user_prompt,
    prepare_runtime,
    start_run,
    validate_execution_preconditions,
)
from .stream import consume_stream
from .types import ExecuteRunResult


async def execute_run(
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
) -> ExecuteRunResult:
    run, conversation, agent = await load_run_context(
        db,
        conversation_id=conversation_id,
        run_id=run_id,
        lock_run=True,
    )
    skills = await load_agent_skills(db, agent)
    available_files = await load_available_files(db, conversation)
    event_sink = sink or NullSink(run_id=run.id, conversation_id=conversation.id)
    run_workspace_id = run.workspace_id
    run_user_id = run.user_id
    started = False
    usage_accumulator = usage if usage is not None else RunUsage()
    invocation_started_at = await db.scalar(select(func.clock_timestamp()))
    if invocation_started_at is None:
        raise RuntimeError("Database did not return an invocation timestamp")
    usage_baseline = usage_values(usage_accumulator)
    metering: AgentRunMeteringContext | None = None

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
                _user, workspace, _membership = await load_actor_context(db, run)
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
        await event_sink.emit(RunStatusEvent(status=RUN_STATUS_RUNNING))

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
        )
        built_agent = prepared.built_agent
        resolved_model = built_agent.runtime_agent.resolved_model
        metering = AgentRunMeteringContext(
            invocation_started_at=invocation_started_at,
            baseline=usage_baseline,
            usage=usage_accumulator,
            provider=resolved_model.provider,
            model=resolved_model.model,
        )
        eager_tool_return_ids = await persist_eager_denied_tool_results(
            db,
            conversation=conversation,
            run_id=run.id,
            message_history=built_agent.history,
            deferred_tool_results=deferred_tool_results,
        )
        await db.commit()

        # Tool calls share the run-scoped AsyncSession, which forbids concurrent use, so parallel tool calls from one model response run one at a time.
        live_deferred_result_ids: set[str] = set()
        with PydanticAgent.parallel_tool_call_execution_mode("sequential"):
            async with built_agent.runtime_agent.agent.run_stream_events(
                prepared.user_prompt,
                deps=prepared.deps,
                message_history=built_agent.history,
                deferred_tool_results=deferred_tool_results,
                conversation_id=str(conversation.id),
                usage_limits=built_agent.runtime_agent.usage_limits,
                usage=usage_accumulator,
            ) as stream:
                terminal_result = await consume_stream(
                    stream,
                    deps=prepared.deps,
                    skills=skills,
                    run=run,
                    deferred_tool_results=deferred_tool_results,
                    event_sink=event_sink,
                    live_deferred_result_ids=live_deferred_result_ids,
                )

        if terminal_result is None:
            raise RuntimeError("Pydantic AI stream ended without a terminal result")

        usage_event = AIUsageEventData(
            workspace_id=run.workspace_id,
            provider=resolved_model.provider,
            model=resolved_model.model,
            purpose=PURPOSE_AGENT_RUN,
            agent_id=run.agent_id,
            user_id=run.user_id,
            run_id=run.id,
            conversation_id=conversation.id,
            **sum_response_usage(list(terminal_result.new_messages())),
        )

        result = await finalize_terminal_run(
            db,
            event_sink=event_sink,
            conversation=conversation,
            run=run,
            terminal_result=terminal_result,
            client_message_id=client_message_id,
            history=built_agent.history,
            deferred_tool_results=deferred_tool_results,
            deps=prepared.deps,
            skip_initial_user_prompt=user_prompt_persisted,
            live_deferred_result_ids=live_deferred_result_ids,
            eager_tool_return_ids=eager_tool_return_ids,
            usage_event=usage_event,
        )
        watermark_key = built_agent.runtime_agent.history_trimmer.watermark_key
        if result.run.status == RUN_STATUS_COMPLETED and watermark_key is not None:
            await safe_enqueue_history_summary(
                conversation_id=conversation.id,
                workspace_id=conversation.workspace_id,
                watermark_key=watermark_key,
            )
        eager_message_count += 1 if eager_tool_return_ids else 0
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
                workspace_id=run_workspace_id,
                user_id=run_user_id,
                metering=metering,
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
            metering=metering,
        )
        raise
    finally:
        clear_agent_run_cancel_request(run_id)
        await event_sink.close()
