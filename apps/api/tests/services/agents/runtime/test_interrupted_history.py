# apps/api/tests/services/agents/runtime/test_interrupted_history.py

"""Tests interrupted transcript retries, bounds, and tenant ownership."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.usage import RunUsage
from sqlalchemy import select

from core.database import set_session_tenant_context
from models.agent_run import AgentRun
from models.conversation import ConversationMessage
from services.agent_runs import start_agent_run
from services.agents.runtime.approval_identity import MAX_PROPOSAL_BYTES
from services.agents.runtime.interrupted_history import (
    InterruptedHistory,
    bounded_interrupted_history,
    interrupted_payload_size,
)
from services.agents.runtime.run_persistence import persist_failed_run, persist_successful_run
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
