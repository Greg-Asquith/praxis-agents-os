# apps/api/services/agents/runtime/persist_interrupted_messages.py

"""Persists interrupted history without changing the run's terminal verdict."""

import asyncio

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_run import AgentRun
from models.conversation import Conversation
from services.agent_runs.domain import RUN_TRIGGER_EVENT, RUN_TRIGGER_SCHEDULED
from services.agents.runtime.interrupted_history import (
    INTERRUPTED_HISTORY_JOB_KIND,
    TRANSCRIPT_INVOCATION_KEY,
    InterruptedHistory,
    bounded_interrupted_history,
)
from services.agents.runtime.persistence import persist_new_messages


class InterruptedHistoryRetryRequiredError(RuntimeError):
    """Requests a fresh settlement transaction after the history connection is lost."""


async def persist_interrupted_messages(
    db: AsyncSession,
    *,
    run: AgentRun,
    history: InterruptedHistory,
    invocation_id: str,
    history_wait: float | None = 1.0,
) -> None:
    """Persists under the family lock; zero queues, and None uses the job's deadline."""
    if not invocation_id:
        raise ValueError("Interrupted history requires its execution identity")
    if (run.metadata_json or {}).get(TRANSCRIPT_INVOCATION_KEY) == invocation_id:
        return
    if history_wait is None:
        await _persist_history(db, run=run, history=history, invocation_id=invocation_id)
        return
    if history_wait == 0:
        await _queue_history(db, run=run, history=history, invocation_id=invocation_id)
        return
    deadline = asyncio.timeout(history_wait)
    try:
        async with db.begin_nested(), deadline:
            previous_timeout = await db.scalar(text("SHOW statement_timeout"))
            await _set_statement_timeout(db, f"{max(1, int(history_wait * 800))}ms")
            await _persist_history(db, run=run, history=history, invocation_id=invocation_id)
            await _set_statement_timeout(db, previous_timeout)
    except (TimeoutError, SQLAlchemyError) as exc:
        statement_timed_out = (
            isinstance(exc, DBAPIError) and getattr(exc.orig, "sqlstate", None) == "57014"
        )
        if not deadline.expired() and not statement_timed_out:
            raise
        if deadline.expired() and isinstance(exc, SQLAlchemyError):
            raise InterruptedHistoryRetryRequiredError from exc
        # A cancelled asyncpg query can invalidate the connection during savepoint rollback.
        try:
            await db.refresh(run)
        except SQLAlchemyError as refresh_error:
            raise InterruptedHistoryRetryRequiredError from refresh_error
        await _queue_history(db, run=run, history=history, invocation_id=invocation_id)


async def _queue_history(
    db: AsyncSession, *, run: AgentRun, history: InterruptedHistory, invocation_id: str
) -> None:
    payload = bounded_interrupted_history(
        history,
        workspace_id=run.workspace_id,
        user_id=run.user_id,
        conversation_id=run.conversation_id,
        run_id=run.id,
        invocation_id=invocation_id,
    )
    if payload.omitted_messages:
        run.metadata_json = {
            **(run.metadata_json or {}),
            "interrupted_history_truncation": {
                "invocation_id": invocation_id,
                "omitted_messages": payload.omitted_messages,
            },
        }
    from services.jobs.enqueue_job import enqueue_job

    await enqueue_job(
        db,
        kind=INTERRUPTED_HISTORY_JOB_KIND,
        workspace_id=run.workspace_id,
        initiated_by_user_id=run.user_id,
        subject_type="agent_run",
        subject_id=run.id,
        payload=payload.model_dump(mode="json"),
        content_hash=invocation_id,
    )


async def _persist_history(
    db: AsyncSession, *, run: AgentRun, history: InterruptedHistory, invocation_id: str
) -> None:
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == run.conversation_id,
            Conversation.workspace_id == run.workspace_id,
            Conversation.deleted.is_(False),
        )
    )
    if conversation is None:
        return
    rows = await persist_new_messages(
        db,
        conversation=conversation,
        run_id=run.id,
        messages=history.prepared_messages(),
        tool_approval_metadata_by_call_id=history.tool_approval_metadata_by_call_id,
    )
    if rows and run.trigger in {RUN_TRIGGER_SCHEDULED, RUN_TRIGGER_EVENT}:
        conversation.unread = True
    run.metadata_json = {**(run.metadata_json or {}), TRANSCRIPT_INVOCATION_KEY: invocation_id}
    await db.flush()


async def _set_statement_timeout(db: AsyncSession, value: str) -> None:
    await db.execute(text("SELECT set_config('statement_timeout', :value, true)"), {"value": value})
