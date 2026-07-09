# apps/api/services/agents/runtime/run_persistence.py

"""Persist runtime execution outcomes back to agent-run state."""

import logging
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from pydantic_ai import DeferredToolRequests
from pydantic_core import to_jsonable_python
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import configure_async_db_session, get_async_db_session_factory
from core.exceptions.general import ConflictError
from models.agent_run import AgentRun
from models.conversation import Conversation
from services.agent_runs.await_approval import mark_run_awaiting_approval
from services.agent_runs.cancel import cancel_agent_run
from services.agent_runs.complete import complete_agent_run
from services.agent_runs.domain import (
    RUN_STATUS_RUNNING,
    RUN_TRIGGER_SCHEDULED,
    RunUsageSnapshot,
    is_terminal,
)
from services.agent_runs.fail import fail_agent_run
from services.agent_runs.record_usage import record_run_usage
from services.agents.runtime.approval_state import (
    build_suspended_run_metadata,
    clear_suspended_run_metadata,
)
from services.agents.runtime.load_context import load_run_context
from services.agents.runtime.persistence import persist_new_messages, without_initial_user_prompt
from services.agents.runtime.staged_tool_content import stage_write_file_approval_content

logger = logging.getLogger(__name__)


async def persist_suspended_run(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    run_id: UUID,
    terminal_result: Any,
    deferred_tool_requests: DeferredToolRequests,
    client_message_id: str | None,
    skip_initial_user_prompt: bool = False,
) -> tuple[AgentRun, int, DeferredToolRequests]:
    """Store messages and suspend a running run for human tool approval."""
    run, conversation, _agent = await load_run_context(
        db,
        conversation_id=conversation_id,
        run_id=run_id,
        populate_existing=True,
    )
    if is_terminal(run.status):
        await db.commit()
        return run, 0, deferred_tool_requests
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
    run.metadata_json = build_suspended_run_metadata(
        run=run,
        conversation=conversation,
        message_history=staged.all_messages,
        deferred_tool_requests=staged.deferred_tool_requests,
    )
    await mark_run_awaiting_approval(db, run)
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
) -> tuple[AgentRun, int]:
    """Store messages and complete a running run."""
    run, conversation, _agent = await load_run_context(
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
            details={"run_id": str(run.id), "run_status": run.status},
        )

    new_messages = terminal_result.new_messages()
    messages_to_persist = (
        without_initial_user_prompt(new_messages) if skip_initial_user_prompt else new_messages
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
    run.metadata_json = clear_suspended_run_metadata(run)
    await complete_agent_run(db, run)
    await db.commit()
    return run, len(persisted_messages)


async def persist_failed_run(
    db: AsyncSession,
    *,
    run_id: UUID,
    error_code: str,
    error_message: str,
) -> AgentRun | None:
    """Mark a started run failed without losing diagnostic state."""
    run = await db.get(AgentRun, run_id, populate_existing=True)
    if run is None:
        await db.commit()
        return None
    if is_terminal(run.status):
        await db.commit()
        return run

    run.metadata_json = clear_suspended_run_metadata(run)
    await fail_agent_run(
        db,
        run,
        error_code=error_code,
        error_message=error_message,
    )
    await db.commit()
    return run


async def persist_cancelled_run(run_id: UUID) -> AgentRun | None:
    """Mark a run cancelled in an isolated transaction without raising to unwind code."""
    try:
        session_factory = get_async_db_session_factory()
        async with session_factory() as db:
            await configure_async_db_session(db)
            run = await db.get(AgentRun, run_id, populate_existing=True)
            if run is None:
                await db.commit()
                return None
            if is_terminal(run.status):
                await db.commit()
                return run

            run.metadata_json = clear_suspended_run_metadata(run)
            await cancel_agent_run(db, run)
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


def _mark_background_output_unread(
    run: AgentRun,
    conversation: Conversation,
    *,
    persisted_messages_count: int,
) -> None:
    if run.trigger == RUN_TRIGGER_SCHEDULED and persisted_messages_count > 0:
        conversation.unread = True
