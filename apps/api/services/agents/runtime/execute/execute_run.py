# apps/api/services/agents/runtime/execute/execute_run.py

"""Execute one agent turn through Pydantic AI."""

import asyncio
from collections.abc import Sequence
from dataclasses import replace
from uuid import UUID, uuid4

from pydantic_ai import Agent as PydanticAgent, DeferredToolResults
from pydantic_ai.messages import ModelMessage, UserContent
from pydantic_ai.models import Model
from pydantic_ai.usage import RunUsage
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from services.agent_runs.domain import (
    RUN_STATUS_COMPLETED,
    RUN_STATUS_PENDING,
    RUN_STATUS_RUNNING,
    RUN_TRIGGER_DELEGATED,
    RUN_TRIGGER_INTERACTIVE,
)
from services.agents.runtime.cancellation import (
    clear_agent_run_cancel_request,
)
from services.agents.runtime.execution_control import (
    ExecutionControl,
    ExecutionInterruptedError,
    ExecutionPhase,
    InterruptionReason,
    execution_control_for_run,
)
from services.agents.runtime.heartbeat import heartbeat_agent_run_lease, stop_agent_run_heartbeat
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
from services.agents.runtime.usage_limits import BudgetLimitExceeded, EffectiveUsageLimits
from services.ai_usage.agent_run_accounting import AgentRunMeteringContext
from services.ai_usage.utils import usage_values
from services.conversation_summaries.safe_enqueue_history_summary import (
    safe_enqueue_history_summary,
)

from .finalize import (
    CANCEL_FINALIZE_TIMEOUT,
    finalize_terminal_run,
)
from .settle_failure import settle_failure
from .settle_interruption import settle_interruption
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
    inherited_usage_limits: EffectiveUsageLimits | None = None,
    parent_metering: AgentRunMeteringContext | None = None,
    execution_control: ExecutionControl | None = None,
    root_execution: ExecutionControl | None = None,
) -> ExecuteRunResult:
    invocation_id = UUID(owner_instance_id) if owner_instance_id is not None else uuid4()
    owner_instance_id = str(invocation_id)
    usage_accumulator = usage if usage is not None else RunUsage()
    usage_baseline = usage_values(usage_accumulator)
    event_sink = sink or NullSink(run_id=run_id, conversation_id=conversation_id)
    run_workspace_id = execution_control.workspace_id if execution_control else None
    run_user_id = execution_control.user_id if execution_control else None
    is_delegated = root_execution is not None
    started = False
    heartbeat_stop = asyncio.Event()
    heartbeat_task: asyncio.Task | None = None
    metering: AgentRunMeteringContext | None = None

    try:
        try:
            deadline = (
                execution_control.deadline
                if execution_control
                else (
                    root_execution.deadline
                    if root_execution
                    else asyncio.get_running_loop().time() + settings.AGENT_RUN_MAX_DURATION_SECONDS
                )
            )
            execution_timeout = asyncio.timeout_at(deadline)
            async with execution_timeout:
                run, conversation, agent = await load_run_context(
                    db,
                    conversation_id=conversation_id,
                    run_id=run_id,
                    lock_run=True,
                )
                run_workspace_id, run_user_id = run.workspace_id, run.user_id
                is_delegated = run.trigger == RUN_TRIGGER_DELEGATED
                validate_execution_preconditions(
                    run,
                    user_prompt=user_prompt,
                    message_history=message_history,
                    deferred_tool_results=deferred_tool_results,
                    expected_status=expected_status,
                )

                await start_run(db, run, owner_instance_id=owner_instance_id)
                started = True
                execution_control = execution_control or execution_control_for_run(
                    run, root=root_execution
                )
                execution_control.phase = ExecutionPhase.EXECUTING
                heartbeat_task = asyncio.create_task(
                    heartbeat_agent_run_lease(
                        stop=heartbeat_stop,
                        cancel_target=asyncio.current_task(),
                        execution_control=execution_control,
                    )
                )
                execution_timeout.reschedule(execution_control.deadline)
                skills = await load_agent_skills(db, agent)
                available_files = await load_available_files(db, conversation)
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
                            conversation_id=conversation.id,
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
                    inherited_usage_limits=inherited_usage_limits,
                )
                built_agent = prepared.built_agent
                resolved_model = built_agent.runtime_agent.resolved_model
                metering = AgentRunMeteringContext(
                    invocation_id=invocation_id,
                    parent=parent_metering,
                    baseline=usage_baseline,
                    usage=usage_accumulator,
                    provider=resolved_model.provider,
                    model=resolved_model.model,
                )
                metering.capture_run(run)
                prepared = replace(
                    prepared,
                    deps=replace(
                        prepared.deps, metering=metering, execution_control=execution_control
                    ),
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
                built_agent.runtime_agent.usage_limits.check_tokens(usage_accumulator)
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

            execution_control.phase = ExecutionPhase.FINALISING
            metering.freeze()
            usage_event = metering.event()

            async with asyncio.timeout(CANCEL_FINALIZE_TIMEOUT):
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
        except Exception as exc:
            if (
                isinstance(exc, TimeoutError)
                and execution_control is not None
                and execution_timeout.expired()
            ):
                execution_control.interrupt(InterruptionReason.DURATION_EXPIRED)
                exc = ExecutionInterruptedError(InterruptionReason.DURATION_EXPIRED)
            if execution_control is not None:
                execution_control.phase = ExecutionPhase.FINALISING
            failed_run = await settle_failure(
                db,
                event_sink=event_sink,
                started=started or execution_control is not None,
                owner_instance_id=owner_instance_id,
                run_id=run_id,
                exc=exc,
                metering=metering,
                max_wait=CANCEL_FINALIZE_TIMEOUT,
            )
            if isinstance(exc, BudgetLimitExceeded) and exc.inherited:
                raise
            if is_delegated and failed_run is not None:
                return ExecuteRunResult(run=failed_run, output=None, new_message_count=0)
            raise
    except asyncio.CancelledError as exc:
        if run_workspace_id is not None and run_user_id is not None:
            await settle_interruption(
                db,
                exc=exc,
                event_sink=event_sink,
                run_id=run_id,
                workspace_id=run_workspace_id,
                user_id=run_user_id,
                execution_control=execution_control,
                metering=metering,
                max_wait=CANCEL_FINALIZE_TIMEOUT,
            )
        raise
    finally:
        await stop_agent_run_heartbeat(heartbeat_stop, heartbeat_task)
        if execution_control is not None:
            execution_control.phase = ExecutionPhase.RELEASED
        clear_agent_run_cancel_request(run_id)
        await event_sink.close()
