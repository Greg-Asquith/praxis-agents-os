# apps/api/tests/services/agents/runtime/test_interrupted_history.py

"""Tests interrupted transcript retries, bounds, and tenant ownership."""

import asyncio
import importlib
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.usage import RunUsage
from sqlalchemy import select

from core.database import set_session_tenant_context
from models.agent_run import AgentRun
from models.conversation import Conversation, ConversationMessage
from models.jobs import Job
from services.agent_runs import start_agent_run
from services.agents.runtime.approval_identity import MAX_PROPOSAL_BYTES
from services.agents.runtime.interrupted_history import (
    INTERRUPTED_HISTORY_JOB_KIND,
    TRANSCRIPT_INVOCATION_KEY,
    InterruptedHistory,
    bounded_interrupted_history,
    interrupted_payload_size,
)
from services.agents.runtime.run_persistence import persist_failed_run, persist_successful_run
from services.jobs.handlers.persist_interrupted_history import persist_interrupted_history
from tests.support.scenario import build_scenario_agent


def test_bounded_history_counts_approval_metadata_and_keeps_latest_suffix():
    history = InterruptedHistory(
        messages=[
            ModelResponse(parts=[ToolCallPart("write_file", {}, "old")]),
            ModelRequest(parts=[ToolReturnPart("write_file", "saved", "old")]),
            ModelResponse(parts=[TextPart("latest")]),
        ],
        tool_approval_metadata_by_call_id={"old": {"large": "x" * MAX_PROPOSAL_BYTES}},
    )
    payload = bounded_interrupted_history(
        history,
        workspace_id=uuid4(),
        user_id=uuid4(),
        conversation_id=uuid4(),
        run_id=uuid4(),
        invocation_id=str(uuid4()),
    )
    assert len(payload.model_dump_json().encode()) <= MAX_PROPOSAL_BYTES
    assert payload.omitted_messages == 2
    assert payload.messages[0]["parts"][0]["content"] == "latest"
    assert payload.approval_metadata == {}


def test_resumed_tool_call_closes_without_duplicating_saved_call_or_denial():
    messages = InterruptedHistory(
        messages=[],
        resumed_tool_calls=[
            ToolCallPart("write_file", {}, "write"),
            ToolCallPart("write_file", {}, "denied"),
        ],
        eager_tool_return_ids={"denied"},
    ).prepared_messages()
    assert len(messages) == 1
    assert len(messages[0].parts) == 1
    assert messages[0].parts[0].tool_call_id == "write"
    assert messages[0].parts[0].outcome == "interrupted"


@pytest.mark.asyncio
@pytest.mark.parametrize("lock_conversation", [False, True])
async def test_timeout_rolls_back_partial_rows_and_job_retries_once(
    committed_db_session_factory, monkeypatch, lock_conversation
):
    context = await build_scenario_agent(committed_db_session_factory)
    invocation = str(uuid4())
    history = InterruptedHistory(
        messages=[ModelResponse(parts=[ToolCallPart("write_file", {}, "write")])],
        tool_approval_metadata_by_call_id={"write": {"approved": True}},
    )
    module = importlib.import_module("services.agents.runtime.persist_interrupted_messages")
    original = module.persist_new_messages

    async def slow_write(*args, **kwargs):
        await original(*args, **kwargs)
        await asyncio.Event().wait()

    async with committed_db_session_factory() as db, committed_db_session_factory() as blocker:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        run = await db.get(AgentRun, context.run_id)
        run.owner_instance_id = invocation
        await start_agent_run(db, run)
        await db.commit()
        if lock_conversation:
            await set_session_tenant_context(
                blocker, workspace_id=context.workspace_id, user_id=context.user_id
            )
            await blocker.execute(
                select(Conversation)
                .where(Conversation.id == context.conversation_id)
                .with_for_update()
            )
        else:
            monkeypatch.setattr(module, "persist_new_messages", slow_write)
        async with asyncio.timeout(2):
            result = await persist_failed_run(
                db,
                run_id=run.id,
                error_code="usage_limit_exceeded",
                error_message="Stopped",
                owner_instance_id=invocation,
                interrupted_history=history,
                history_wait=0.2,
            )
        assert result.status == "failed"
        assert (
            list(
                await db.scalars(
                    select(ConversationMessage).where(
                        ConversationMessage.conversation_id == context.conversation_id
                    )
                )
            )
            == []
        )
        job = await db.scalar(
            select(Job).where(
                Job.kind == INTERRUPTED_HISTORY_JOB_KIND, Job.subject_id == context.run_id
            )
        )
        assert job is not None
        await blocker.rollback()
        monkeypatch.setattr(module, "persist_new_messages", original)
        await persist_interrupted_history(db, job)
        await db.commit()
        await persist_interrupted_history(db, job)
        await db.commit()
        rows = list(
            await db.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == context.conversation_id)
                .order_by(ConversationMessage.sequence)
            )
        )
        assert len(rows) == 2
        assert rows[1].parts["parts"][0]["outcome"] == "interrupted"
        assert rows[1].metadata_json["approval_results"]["write"] == {"approved": True}
        assert run.metadata_json[TRANSCRIPT_INVOCATION_KEY] == invocation
        assert run.status == "failed"
        job.initiated_by_user_id = uuid4()
        with pytest.raises(ValueError, match="identity"):
            await persist_interrupted_history(db, job)
        await db.rollback()


@pytest.mark.asyncio
async def test_interrupted_history_preserves_first_verdict_and_rejects_stale_owner(
    committed_db_session_factory,
):
    context = await build_scenario_agent(committed_db_session_factory)
    invocation = str(uuid4())
    history = InterruptedHistory(messages=[ModelResponse(parts=[TextPart("produced")])])
    async with committed_db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        run = await db.get(AgentRun, context.run_id)
        run.owner_instance_id = invocation
        await start_agent_run(db, run)
        await db.commit()
        for owner in [str(uuid4()), invocation, invocation]:
            await persist_failed_run(
                db,
                run_id=run.id,
                error_code="first" if owner == invocation else "stale",
                error_message="Stopped",
                owner_instance_id=owner,
                interrupted_history=history,
            )
        assert run.error_code == "first"
        assert (
            len(
                list(
                    await db.scalars(
                        select(ConversationMessage).where(
                            ConversationMessage.conversation_id == context.conversation_id
                        )
                    )
                )
            )
            == 1
        )


def test_empty_interrupted_response_is_not_a_transcript_row():
    partial = ModelResponse(parts=[TextPart("partial")])
    history = InterruptedHistory(messages=[partial, ModelResponse(parts=[])])
    assert history.prepared_messages() == [partial]


def test_payload_limit_counts_escaped_unicode():
    history = InterruptedHistory(
        messages=[
            ModelResponse(parts=[TextPart("漢" * (MAX_PROPOSAL_BYTES // 4))]),
            ModelResponse(parts=[TextPart("latest")]),
        ]
    )
    payload = bounded_interrupted_history(
        history,
        workspace_id=uuid4(),
        user_id=uuid4(),
        conversation_id=uuid4(),
        run_id=uuid4(),
        invocation_id=str(uuid4()),
    )
    assert payload.omitted_messages == 1
    assert interrupted_payload_size(payload) <= MAX_PROPOSAL_BYTES


@pytest.mark.asyncio
async def test_failure_after_success_does_not_duplicate_invocation_messages(
    committed_db_session_factory,
):
    context = await build_scenario_agent(committed_db_session_factory)
    invocation = str(uuid4())
    messages = [ModelResponse(parts=[TextPart("completed")])]
    async with committed_db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        run = await db.get(AgentRun, context.run_id)
        run.owner_instance_id = invocation
        await start_agent_run(db, run)
        await db.commit()
        await persist_successful_run(
            db,
            conversation_id=context.conversation_id,
            run_id=run.id,
            terminal_result=SimpleNamespace(new_messages=lambda: messages, usage=RunUsage()),
            client_message_id=None,
        )
        await persist_failed_run(
            db,
            run_id=run.id,
            error_code="late",
            error_message="Stopped",
            owner_instance_id=invocation,
            interrupted_history=InterruptedHistory(messages=messages),
        )
        rows = list(
            await db.scalars(
                select(ConversationMessage).where(
                    ConversationMessage.conversation_id == context.conversation_id
                )
            )
        )
        assert len(rows) == 1
        assert run.status == "completed"


@pytest.mark.asyncio
async def test_queue_only_fallback_records_truncation_before_job_execution(monkeypatch):
    from unittest.mock import AsyncMock

    from services.agents.runtime.persist_interrupted_messages import persist_interrupted_messages

    enqueue_module = importlib.import_module("services.jobs.enqueue_job")
    enqueue = AsyncMock()
    monkeypatch.setattr(enqueue_module, "enqueue_job", enqueue)
    run = AgentRun(
        id=uuid4(), workspace_id=uuid4(), user_id=uuid4(), conversation_id=uuid4(), metadata_json={}
    )
    invocation = str(uuid4())
    history = InterruptedHistory(
        messages=[
            ModelResponse(parts=[TextPart("x" * MAX_PROPOSAL_BYTES)]),
            ModelResponse(parts=[TextPart("latest")]),
        ]
    )
    await persist_interrupted_messages(
        object(), run=run, history=history, invocation_id=invocation, history_wait=0
    )
    assert enqueue.await_count == 1
    assert run.metadata_json["interrupted_history_truncation"]["omitted_messages"] == 1
    assert enqueue.call_args.kwargs["payload"]["messages"][0]["parts"][0]["content"] == "latest"


@pytest.mark.asyncio
@pytest.mark.parametrize("teardown_fails", [False, True])
async def test_python_deadline_requests_fresh_session_after_connection_invalidation(
    monkeypatch, teardown_fails
):
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    from sqlalchemy.exc import PendingRollbackError

    from services.agents.runtime.persist_interrupted_messages import (
        InterruptedHistoryRetryRequiredError,
        persist_interrupted_messages,
    )

    @asynccontextmanager
    async def nested():
        try:
            yield
        finally:
            if teardown_fails:
                raise PendingRollbackError("connection invalidated")

    async def blocked_write(*args, **kwargs):
        await asyncio.Event().wait()

    module = importlib.import_module("services.agents.runtime.persist_interrupted_messages")
    monkeypatch.setattr(module, "_persist_history", blocked_write)
    db = SimpleNamespace(
        begin_nested=nested,
        scalar=AsyncMock(return_value="0"),
        execute=AsyncMock(),
        refresh=AsyncMock(side_effect=PendingRollbackError("connection invalidated")),
    )
    with pytest.raises(InterruptedHistoryRetryRequiredError):
        await persist_interrupted_messages(
            db,
            run=SimpleNamespace(metadata_json={}),
            history=InterruptedHistory(messages=[]),
            invocation_id=str(uuid4()),
            history_wait=0.01,
        )
