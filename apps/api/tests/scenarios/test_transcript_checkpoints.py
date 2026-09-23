"""Completed model and tool steps survive without terminal transcript writes."""

import asyncio
import importlib
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.capabilities.hooks import HookTimeoutError
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import DeltaToolCall, FunctionModel
from sqlalchemy import select

from core.database import set_session_tenant_context
from models.agent_run import AgentRun
from models.conversation import ConversationMessage
from services.agents.runtime.approval_state import load_suspended_run_state
from services.agents.runtime.tools.registry import RUNTIME_TOOL_CATALOG
from tests.support.scenario import (
    ScenarioBarrier,
    ToolCall,
    ToolTurn,
    build_scenario_agent,
    run_scenario,
    scripted_model,
)


@pytest.mark.parametrize("finish", ["success", "shutdown"])
async def test_completed_steps_are_durable_before_next_model_response(
    committed_db_session_factory, monkeypatch, finish
):
    context = await build_scenario_agent(
        committed_db_session_factory,
        tool_names=["scenario_external_write"],
        trigger="scheduled",
        metadata={"envelope": {"side_effect_policy": "allow"}},
    )
    barrier = ScenarioBarrier()
    request_count = 0

    async def read_rows():
        async with committed_db_session_factory() as db:
            await set_session_tenant_context(
                db, workspace_id=context.workspace_id, user_id=context.user_id
            )
            run = await db.get(AgentRun, context.run_id)
            rows = list(
                await db.scalars(
                    select(ConversationMessage)
                    .where(
                        ConversationMessage.conversation_id == context.conversation_id,
                    )
                    .order_by(ConversationMessage.sequence)
                )
            )
            return run, rows

    async def write(value: str = "ok"):
        run, rows = await read_rows()
        assert run.status == "running"
        assert [row.role for row in rows] == ["user", "assistant"]
        assert rows[-1].parts["parts"][0]["tool_call_id"] == "saved-call"
        assert run.usage_json["requests"] == 1
        return {"ok": value == "report"}

    definition = RUNTIME_TOOL_CATALOG["scenario_external_write"]
    monkeypatch.setitem(RUNTIME_TOOL_CATALOG, definition.name, replace(definition, function=write))

    async def stream(_messages, _info):
        nonlocal request_count
        request_count += 1
        if request_count == 1:
            yield {
                0: DeltaToolCall(
                    name=definition.name, json_args='{"value":"report"}', tool_call_id="saved-call"
                )
            }
        else:
            await barrier.pause()
            yield "Saved."

    async with barrier.running(
        run_scenario(
            committed_db_session_factory,
            context,
            model=FunctionModel(stream_function=stream),
        )
    ) as task:
        await asyncio.wait_for(barrier.reached.wait(), timeout=5)
        run, rows = await read_rows()
        assert run.status == "running"
        assert [row.role for row in rows] == ["user", "assistant", "tool"]
        assert rows[-1].parts["parts"][0]["content"] == {"ok": True}
        assert run.usage_json["tool_calls"] == 1
        saved_ids = [row.id for row in rows]
        if finish == "shutdown":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            barrier.release.set()
            result = await task
            assert result.execute_result.new_message_count == 4
            assert len(result.tool_calls(definition.name)) == 1
            assert len(result.tool_returns(definition.name)) == 1

    run, rows = await read_rows()
    assert [row.id for row in rows[:3]] == saved_ids
    assert len(rows) == (4 if finish == "success" else 3)
    assert all(row.metadata_json["agent_run_id"] == str(context.run_id) for row in rows)
    assert [row.sequence for row in rows] == list(range(1, len(rows) + 1))
    assert run.status == ("completed" if finish == "success" else "failed")


async def test_checkpointed_write_approval_stages_once_and_updates_saved_call(
    committed_db_session_factory, monkeypatch
):
    staged_module = importlib.import_module("services.agents.runtime.staged_tool_content")
    stage = AsyncMock(wraps=staged_module._stage_write_args)
    monkeypatch.setattr(staged_module, "_stage_write_args", stage)
    context = await build_scenario_agent(committed_db_session_factory, tool_names=["write_file"])
    result = await run_scenario(
        committed_db_session_factory,
        context,
        model=scripted_model(
            turns=[
                ToolTurn(
                    (
                        ToolCall(
                            "write_file",
                            {"name": "checkpoint.md", "content": "Retained approval body"},
                            "write-approval",
                        ),
                    )
                )
            ]
        ),
    )
    assert result.run.status == "awaiting_approval"
    stage.assert_awaited_once()
    assert result.execute_result.new_message_count == 2
    assert len(result.messages) == 2
    [call] = result.tool_calls("write_file")
    assert "content" not in call["args"]
    state = load_suspended_run_state(result.run)
    [approval] = state.deferred_tool_requests.approvals
    assert call["args"]["content_ref"] == approval.args["content_ref"]
    assert "Retained approval body" not in str([row.parts for row in result.messages])
    assert not any(
        isinstance(part, ToolReturnPart)
        for message in state.message_history
        for part in message.parts
    )
    assert (
        sum(
            isinstance(part, ToolCallPart)
            for message in state.message_history
            for part in message.parts
        )
        == 1
    )


@pytest.mark.parametrize("boundary", ["response", "tool_return"])
async def test_checkpoint_timeout_rolls_back_before_interrupted_settlement(
    committed_db_session_factory, monkeypatch, boundary
):
    checkpoint_module = importlib.import_module("services.agents.runtime.checkpoint_messages")
    stream_module = importlib.import_module("services.agents.runtime.execute.stream")
    persist = checkpoint_module.persist_new_messages

    async def blocked_checkpoint(*args, **kwargs):
        rows = await persist(*args, **kwargs)
        message_type = ModelResponse if boundary == "response" else ModelRequest
        if any(isinstance(message, message_type) for message in kwargs["messages"]):
            await asyncio.Event().wait()
        return rows

    monkeypatch.setattr(checkpoint_module, "persist_new_messages", blocked_checkpoint)
    monkeypatch.setattr(stream_module, "CHECKPOINT_TIMEOUT", 0.05)
    context = await build_scenario_agent(
        committed_db_session_factory, tool_names=["test_add_numbers"]
    )
    async with asyncio.timeout(2):
        with pytest.raises(HookTimeoutError):
            await run_scenario(
                committed_db_session_factory,
                context,
                model=scripted_model(
                    turns=[ToolTurn((ToolCall("test_add_numbers", {"a": 2, "b": 3}, "sum"),))]
                ),
            )
    async with committed_db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        run = await db.get(AgentRun, context.run_id)
        rows = list(
            await db.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == context.conversation_id)
                .order_by(ConversationMessage.sequence)
            )
        )
    assert run.status == "failed"
    assert [row.role for row in rows] == ["user", "assistant", "tool"]
    assert rows[1].parts["parts"][0]["tool_call_id"] == "sum"
    returned = rows[-1].parts["parts"][0]
    assert returned["tool_call_id"] == "sum"
    if boundary == "tool_return":
        assert returned["content"] == 5
    else:
        assert returned["outcome"] == "interrupted"


async def test_failed_suspension_closes_checkpointed_approval_beside_completed_tool(
    committed_db_session_factory, monkeypatch
):
    persistence = importlib.import_module("services.agents.runtime.run_persistence")
    monkeypatch.setattr(
        persistence,
        "stage_write_file_approval_content",
        AsyncMock(side_effect=RuntimeError("Staging unavailable")),
    )
    context = await build_scenario_agent(
        committed_db_session_factory,
        tool_names=["test_add_numbers", "scenario_external_write"],
        tool_policies={"scenario_external_write": "approval"},
    )
    with pytest.raises(RuntimeError, match="Staging unavailable"):
        await run_scenario(
            committed_db_session_factory,
            context,
            model=scripted_model(
                turns=[
                    ToolTurn(
                        (
                            ToolCall("scenario_external_write", {"value": "report"}, "pending"),
                            ToolCall("test_add_numbers", {"a": 2, "b": 3}, "completed"),
                        )
                    )
                ]
            ),
        )
    async with committed_db_session_factory() as db:
        await set_session_tenant_context(
            db, workspace_id=context.workspace_id, user_id=context.user_id
        )
        rows = list(
            await db.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == context.conversation_id)
                .order_by(ConversationMessage.sequence)
            )
        )
    returns = {
        part["tool_call_id"]: part
        for row in rows
        for part in row.parts["parts"]
        if part["part_kind"] == "tool-return"
    }
    assert returns["completed"]["content"] == 5
    assert returns["pending"]["outcome"] == "interrupted"
    assert sum(row.role == "assistant" for row in rows) == 1
