# apps/api/services/agents/runtime/run_persistence.py

"""Persist runtime execution outcomes back to agent-run state."""

import logging
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from pydantic import TypeAdapter
from pydantic_ai import DeferredToolRequests
from pydantic_ai.usage import RunUsage
from pydantic_core import to_jsonable_python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import (
    configure_async_db_session,
    get_async_db_session_factory,
    set_session_tenant_context,
)
from core.exceptions.general import ConflictError
from models.agent_run import AgentRun
from models.conversation import Conversation
from services.agent_runs.await_approval import mark_run_awaiting_approval
from services.agent_runs.complete import complete_agent_run
from services.agent_runs.domain import (
    RUN_OUTCOME_GATE_FAILED,
    RUN_OUTCOME_SUCCESS,
    RUN_STATUS_RUNNING,
    RUN_TRIGGER_EVENT,
    RUN_TRIGGER_SCHEDULED,
    RunOutcome,
    RunUsageSnapshot,
    is_terminal,
)
from services.agent_runs.record_usage import record_run_usage
from services.agent_runs.settle_run_family import lock_run_family, settle_run_family
from services.agents.runtime.approval_identity import APPROVAL_REVISION_KEY
from services.agents.runtime.approval_projection import build_approval_graph, project_approval_graph
from services.agents.runtime.approval_state import (
    APPROVAL_STATE_METADATA_KEY,
    build_suspended_run_metadata,
    clear_suspended_run_metadata,
)
from services.agents.runtime.completion_contract import (
    completion_contract_from_run_metadata,
    validate_completion_json,
)
from services.agents.runtime.load_context import load_run_context
from services.agents.runtime.persistence import (
    persist_new_messages,
    without_initial_user_prompt,
    without_tool_returns,
)
from services.agents.runtime.staged_tool_content import stage_write_file_approval_content
from services.ai_usage.agent_run_accounting import AgentRunMeteringContext
from services.ai_usage.domain import AIUsageEventData
from services.ai_usage.record_agent_run_fallback import record_agent_run_fallback
from services.ai_usage.record_in_transaction import record_ai_usage_in_transaction

logger = logging.getLogger(__name__)
_RUN_USAGE_ADAPTER = TypeAdapter(RunUsage)


async def persist_suspended_run(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    run_id: UUID,
    terminal_result: Any,
    deferred_tool_requests: DeferredToolRequests,
    client_message_id: str | None,
    skip_initial_user_prompt: bool = False,
    eager_tool_return_ids: set[str] | None = None,
    usage_event: AIUsageEventData | None = None,
) -> tuple[AgentRun, int, DeferredToolRequests | None]:
    """Store messages and suspend a running run for human tool approval."""
    run, conversation, _agent = await load_run_context(
        db,
        conversation_id=conversation_id,
        run_id=run_id,
        populate_existing=True,
        lock_run=True,
    )
    if (
        usage_event is not None
        and run.owner_instance_id is not None
        and run.owner_instance_id != (usage_event.details or {}).get("invocation_id")
    ):
        await record_ai_usage_in_transaction(db, usage_event)
        await db.commit()
        return run, 0, None
    if is_terminal(run.status):
        final_run, count = await persist_successful_run(
            db,
            conversation_id=conversation_id,
            run_id=run_id,
            terminal_result=terminal_result,
            client_message_id=client_message_id,
            skip_initial_user_prompt=skip_initial_user_prompt,
            eager_tool_return_ids=eager_tool_return_ids,
            usage_event=usage_event,
        )
        return final_run, count, None
    if run.status != RUN_STATUS_RUNNING:
        raise ConflictError(
            "Agent run is no longer running",
            conflicting_resource="agent_run",
            details={"run_id": str(run.id), "run_status": run.status},
        )

    new_messages = terminal_result.new_messages()
    messages_to_persist = (
        without_initial_user_prompt(new_messages) if skip_initial_user_prompt else new_messages
    )
    messages_to_persist = without_tool_returns(
        messages_to_persist,
        tool_call_ids=eager_tool_return_ids or set(),
    )
    staged = await stage_write_file_approval_content(
        workspace_id=run.workspace_id,
        run_id=run.id,
        new_messages=messages_to_persist,
        all_messages=terminal_result.all_messages(),
        deferred_tool_requests=deferred_tool_requests,
    )

    persisted_messages = await persist_new_messages(
        db,
        conversation=conversation,
        run_id=run.id,
        messages=staged.new_messages,
        client_message_id=client_message_id,
    )
    _mark_background_output_unread(
        run,
        conversation,
        persisted_messages_count=len(persisted_messages),
    )
    await record_run_usage(db, run, usage_snapshot(terminal_result.usage))
    if usage_event is not None:
        await record_ai_usage_in_transaction(db, usage_event)
    run.metadata_json = build_suspended_run_metadata(
        run=run,
        conversation=conversation,
        message_history=staged.all_messages,
        deferred_tool_requests=staged.deferred_tool_requests,
    )
    await mark_run_awaiting_approval(db, run)
    if run.parent_run_id is None:
        children = await db.scalars(
            select(AgentRun).where(
                AgentRun.parent_run_id == run.id,
                AgentRun.workspace_id == run.workspace_id,
                AgentRun.user_id == run.user_id,
                AgentRun.deleted == False,  # noqa: E712
            )
        )
        projection = project_approval_graph(
            build_approval_graph(run, {child.id: child for child in children})
        )
        metadata = dict(run.metadata_json)
        metadata[APPROVAL_STATE_METADATA_KEY] = {
            **metadata[APPROVAL_STATE_METADATA_KEY],
            APPROVAL_REVISION_KEY: projection.approval_revision,
        }
        run.metadata_json = metadata
    await db.commit()
    return run, len(persisted_messages), staged.deferred_tool_requests


async def persist_successful_run(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    run_id: UUID,
    terminal_result: Any,
    client_message_id: str | None,
    tool_approval_metadata_by_call_id: Mapping[str, Mapping[str, Any]] | None = None,
    skip_initial_user_prompt: bool = False,
    eager_tool_return_ids: set[str] | None = None,
    usage_event: AIUsageEventData | None = None,
) -> tuple[AgentRun, int]:
    """Store messages and complete a running run."""
    run, conversation, _agent = await load_run_context(
        db,
        conversation_id=conversation_id,
        run_id=run_id,
        populate_existing=True,
        lock_run=True,
    )
    if (
        usage_event is not None
        and run.owner_instance_id is not None
        and run.owner_instance_id != (usage_event.details or {}).get("invocation_id")
    ):
        await record_ai_usage_in_transaction(db, usage_event)
        await db.commit()
        return run, 0
    new_messages = terminal_result.new_messages()
    messages_to_persist = (
        without_initial_user_prompt(new_messages) if skip_initial_user_prompt else new_messages
    )
    messages_to_persist = without_tool_returns(
        messages_to_persist,
        tool_call_ids=eager_tool_return_ids or set(),
    )
    if is_terminal(run.status):
        # Another actor settled the run mid-flight; keep its verdict but still
        # persist the record of what this execution actually did.
        logger.warning(
            "Agent run was settled terminally during execution; persisting messages only",
            extra={"run_id": str(run.id), "run_status": run.status},
        )
        persisted_messages = await persist_new_messages(
            db,
            conversation=conversation,
            run_id=run.id,
            messages=messages_to_persist,
            client_message_id=client_message_id,
            tool_approval_metadata_by_call_id=tool_approval_metadata_by_call_id,
        )
        await record_run_usage(db, run, usage_snapshot(terminal_result.usage))
        if usage_event is not None:
            await record_ai_usage_in_transaction(db, usage_event)
        run.metadata_json = clear_suspended_run_metadata(run)
        await db.commit()
        return run, len(persisted_messages)
    if run.status != RUN_STATUS_RUNNING:
        raise ConflictError(
            "Agent run is no longer running",
            conflicting_resource="agent_run",
            details={"run_id": str(run.id), "run_status": run.status},
        )

    persisted_messages = await persist_new_messages(
        db,
        conversation=conversation,
        run_id=run.id,
        messages=messages_to_persist,
        client_message_id=client_message_id,
        tool_approval_metadata_by_call_id=tool_approval_metadata_by_call_id,
    )
    _mark_background_output_unread(
        run,
        conversation,
        persisted_messages_count=len(persisted_messages),
    )
    await record_run_usage(db, run, usage_snapshot(terminal_result.usage))
    if usage_event is not None:
        await record_ai_usage_in_transaction(db, usage_event)
    family = await lock_run_family(db, run_id=run.id)
    if run.parent_run_id is None and any(not is_terminal(child.status) for child in family[1:]):
        await settle_run_family(
            db,
            run_id=run.id,
            error_code="delegation_requires_recovery",
            error_message="A specialist still needs attention. Review its unfinished work before continuing.",
        )
        await db.commit()
        return run, len(persisted_messages)
    run.metadata_json = clear_suspended_run_metadata(run)
    outcome, completion_json = _successful_run_completion(run)
    await complete_agent_run(
        db,
        run,
        outcome=outcome,
        completion_json=completion_json,
    )
    await db.commit()
    return run, len(persisted_messages)


async def persist_failed_run(
    db: AsyncSession,
    *,
    run_id: UUID,
    error_code: str,
    error_message: str,
    completion_json: dict[str, Any] | None = None,
    metering: AgentRunMeteringContext | None = None,
    owner_instance_id: str | None = None,
) -> AgentRun | None:
    """Mark a started run failed without losing diagnostic state."""
    family = await lock_run_family(db, run_id=run_id)
    run = next((item for item in family if item.id == run_id), None)
    if run is None:
        await db.commit()
        return None
    owner_instance_id = owner_instance_id or (
        str(metering.invocation_id) if metering is not None else None
    )
    if (
        owner_instance_id is not None
        and run.owner_instance_id is not None
        and run.owner_instance_id != owner_instance_id
    ):
        if metering is not None:
            await record_ai_usage_in_transaction(db, metering.event())
        await db.commit()
        return run
    await record_agent_run_fallback(db, run=run, metering=metering)
    if is_terminal(run.status):
        await db.commit()
        return run

    await settle_run_family(
        db,
        run_id=run.id,
        error_code=error_code,
        error_message=error_message,
    )
    if completion_json is not None and run.error_code != "agent_run_resume_requires_recovery":
        recovery = (run.completion_json or {}).get("recovery")
        run.completion_json = validate_completion_json(
            {**completion_json, "recovery": recovery} if recovery is not None else completion_json
        )
    await db.commit()
    return run


async def persist_cancelled_run(
    run_id: UUID,
    *,
    workspace_id: UUID,
    user_id: UUID,
    metering: AgentRunMeteringContext | None = None,
    owner_instance_id: str | None = None,
) -> AgentRun | None:
    """Mark a run cancelled in an isolated transaction without raising to unwind code."""
    try:
        session_factory = get_async_db_session_factory()
        async with session_factory() as db:
            await configure_async_db_session(db)
            await set_session_tenant_context(
                db,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            family = await lock_run_family(db, run_id=run_id)
            run = next((item for item in family if item.id == run_id), None)
            if run is None:
                await db.commit()
                return None
            owner_instance_id = owner_instance_id or (
                str(metering.invocation_id) if metering is not None else None
            )
            if (
                owner_instance_id is not None
                and run.owner_instance_id is not None
                and run.owner_instance_id != owner_instance_id
            ):
                if metering is not None:
                    await record_ai_usage_in_transaction(db, metering.event())
                await db.commit()
                return run
            await record_agent_run_fallback(db, run=run, metering=metering)
            if is_terminal(run.status):
                await db.commit()
                return run

            await settle_run_family(db, run_id=run.id, status="cancelled")
            await db.commit()
            return run
    except Exception:
        logger.warning(
            "Failed to persist cancelled agent run",
            exc_info=True,
            extra={"run_id": str(run_id)},
        )
        return None


def usage_snapshot(usage: Any) -> RunUsageSnapshot:
    """Convert a provider usage object into the run usage columns."""
    raw = to_jsonable_python(usage)
    return RunUsageSnapshot(
        input_tokens=getattr(usage, "input_tokens", None),
        input_tokens_cached=getattr(usage, "cache_read_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
        requests=getattr(usage, "requests", None),
        tool_calls=getattr(usage, "tool_calls", None),
        raw_json=raw if isinstance(raw, dict) else {"usage": raw},
    )


def restored_run_usage(run: AgentRun) -> RunUsage:
    """Rehydrate cumulative Pydantic AI usage for an approval continuation."""
    if run.usage_json is None:
        return RunUsage()
    return _RUN_USAGE_ADAPTER.validate_python(run.usage_json)


def _successful_run_completion(run: AgentRun) -> tuple[RunOutcome, dict[str, Any] | None]:
    if run.trigger != RUN_TRIGGER_SCHEDULED:
        return RUN_OUTCOME_SUCCESS, None
    contract = completion_contract_from_run_metadata(run.metadata_json)
    if contract is None or not contract.required:
        return RUN_OUTCOME_SUCCESS, None
    report = run.completion_json
    if report is None:
        return RUN_OUTCOME_GATE_FAILED, {"error_code": "missing_completion_report"}
    if report.get("status") == "pass":
        return RUN_OUTCOME_SUCCESS, report
    return RUN_OUTCOME_GATE_FAILED, report


def _mark_background_output_unread(
    run: AgentRun,
    conversation: Conversation,
    *,
    persisted_messages_count: int,
) -> None:
    if run.trigger in {RUN_TRIGGER_SCHEDULED, RUN_TRIGGER_EVENT} and persisted_messages_count > 0:
        conversation.unread = True
