"""Runtime planning tool tests."""

import importlib
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.agent import Agent
from models.agent_run import AgentRun
from models.audit_event import AuditEvent
from models.conversation import Conversation, ConversationMessage
from models.conversation_todos import ConversationTodoList
from models.user import User
from models.workspace import Workspace
from services.agent_runs import create_agent_run
from services.agent_runs.domain import RUN_STATUS_COMPLETED
from services.agents.runtime.dispatch import digest_args
from services.agents.runtime.envelope import RunEnvelope
from services.agents.runtime.execute_run import ExecuteRunResult, execute_run
from services.agents.runtime.sinks import CollectingSink
from services.agents.runtime.tools.planning import TodoItemInput
from tests.factories import build_user, build_workspace

pytestmark = pytest.mark.asyncio

execute_run_module = importlib.import_module("services.agents.runtime.execute_run")


@dataclass(frozen=True)
class PlanningRuntimeContext:
    user_id: UUID
    workspace_id: UUID
    agent_id: UUID
    conversation_id: UUID


async def test_write_read_round_trip_and_replace_semantics(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await _create_committed_planning_context(committed_db_session_factory)
    first_items = [{"content": "Draft the plan", "status": "in_progress"}]
    second_items = [
        {"content": "Draft the plan", "status": "completed"},
        {"content": "Review the result", "status": "in_progress"},
    ]

    try:
        await _execute_tool_turn(
            committed_db_session_factory,
            context,
            tool_name="write_todos",
            args={"items": first_items},
        )
        await _execute_tool_turn(
            committed_db_session_factory,
            context,
            tool_name="write_todos",
            args={"items": second_items},
        )
        _result, sink, _run_id = await _execute_tool_turn(
            committed_db_session_factory,
            context,
            tool_name="read_todos",
            args={},
        )

        todo_list = await _todo_list(committed_db_session_factory, context)
        assert todo_list is not None
        assert todo_list.items == second_items
        tool_results = [event for event in sink.events if event.event == "tool.result"]
        assert tool_results[-1].data["result"]["items"] == second_items
    finally:
        await _delete_committed_planning_context(committed_db_session_factory, context)


async def test_write_todos_rejects_caps_and_bad_status(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    cap_context = await _create_committed_planning_context(committed_db_session_factory)
    status_context = await _create_committed_planning_context(committed_db_session_factory)
    too_many = [
        {"content": f"Item {index}", "status": "pending"}
        for index in range(51)
    ]
    cap_messages: list[ModelMessage] = []
    status_messages: list[ModelMessage] = []

    try:
        cap_result, _sink, _run_id = await _execute_tool_turn(
            committed_db_session_factory,
            cap_context,
            tool_name="write_todos",
            args={"items": too_many},
            final_text="cap recovered",
            seen_messages=cap_messages,
        )
        status_result, _sink, _run_id = await _execute_tool_turn(
            committed_db_session_factory,
            status_context,
            tool_name="write_todos",
            args={"items": [{"content": "Bad status", "status": "blocked"}]},
            final_text="status recovered",
            seen_messages=status_messages,
        )

        assert cap_result.output == "cap recovered"
        assert status_result.output == "status recovered"
        assert await _todo_list(committed_db_session_factory, cap_context) is None
        assert await _todo_list(committed_db_session_factory, status_context) is None
        assert "limited to 50" in " ".join(map(str, cap_messages))
        assert "pending" in " ".join(map(str, status_messages))
    finally:
        await _delete_committed_planning_context(
            committed_db_session_factory,
            cap_context,
        )
        await _delete_committed_planning_context(
            committed_db_session_factory,
            status_context,
        )


async def test_todos_are_conversation_scoped(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await _create_committed_planning_context(committed_db_session_factory)
    other_context = await _create_second_conversation_context(
        committed_db_session_factory,
        context,
    )
    items = [{"content": "Only the first conversation sees this", "status": "pending"}]

    try:
        await _execute_tool_turn(
            committed_db_session_factory,
            context,
            tool_name="write_todos",
            args={"items": items},
        )
        _result, sink, _run_id = await _execute_tool_turn(
            committed_db_session_factory,
            other_context,
            tool_name="read_todos",
            args={},
        )

        tool_results = [event for event in sink.events if event.event == "tool.result"]
        assert tool_results[-1].data["result"] == {
            "items": [],
            "counts": {"pending": 0, "in_progress": 0, "completed": 0},
        }
    finally:
        await _delete_committed_planning_context(
            committed_db_session_factory,
            other_context,
            delete_shared=False,
        )
        await _delete_committed_planning_context(committed_db_session_factory, context)


async def test_write_todos_audit_uses_digest_only(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    context = await _create_committed_planning_context(committed_db_session_factory)
    marker = f"todo-secret-{uuid4().hex}"
    items = [{"content": marker, "status": "pending"}]

    try:
        _result, _sink, run_id = await _execute_tool_turn(
            committed_db_session_factory,
            context,
            tool_name="write_todos",
            args={"items": items},
        )

        [event] = await _tool_audit_events(
            committed_db_session_factory,
            context,
            run_id=run_id,
            tool_name="write_todos",
        )
        expected_sha, expected_bytes = digest_args(
            {"items": [TodoItemInput(content=marker, status="pending")]}
        )
        assert event.status == "success"
        assert event.details["outcome"] == "completed"
        assert event.details["args_sha256"] == expected_sha
        assert event.details["args_bytes"] == expected_bytes
        assert "args" not in event.details
        assert marker not in str(event.details)
    finally:
        await _delete_committed_planning_context(committed_db_session_factory, context)


async def test_write_todos_denied_by_envelope_before_execution(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = await _create_committed_planning_context(committed_db_session_factory)
    monkeypatch.setattr(
        execute_run_module,
        "build_run_envelope",
        lambda _run: RunEnvelope(
            principal="interactive",
            side_effect_policy="deny",
        ),
    )

    try:
        result, _sink, run_id = await _execute_tool_turn(
            committed_db_session_factory,
            context,
            tool_name="write_todos",
            args={"items": [{"content": "Denied", "status": "pending"}]},
            final_text="denied recovered",
        )

        assert result.output == "denied recovered"
        assert await _todo_list(committed_db_session_factory, context) is None
        [event] = await _tool_audit_events(
            committed_db_session_factory,
            context,
            run_id=run_id,
            tool_name="write_todos",
        )
        assert event.status == "denied"
        assert event.details["outcome"] == "denied_envelope"
    finally:
        await _delete_committed_planning_context(committed_db_session_factory, context)


async def _create_committed_planning_context(
    session_factory: async_sessionmaker[AsyncSession],
) -> PlanningRuntimeContext:
    async with session_factory() as db:
        user = build_user(email=f"planning-runtime-{uuid4().hex}@example.com")
        workspace = build_workspace(slug=f"planning-runtime-{uuid4().hex[:8]}")
        db.add_all([user, workspace])
        await db.flush()

        agent = Agent(
            name="Planning Runtime Agent",
            slug=f"planning-runtime-agent-{uuid4().hex[:8]}",
            instructions="Reply plainly.",
            workspace_id=workspace.id,
            created_by=user.id,
            model_provider="openai",
            model="gpt-5.4-mini",
            tool_names=[],
        )
        db.add(agent)
        await db.flush()

        conversation = Conversation(
            user_id=user.id,
            workspace_id=workspace.id,
            created_by=user.id,
            active_agent_id=agent.id,
        )
        db.add(conversation)
        await db.commit()

    return PlanningRuntimeContext(
        user_id=user.id,
        workspace_id=workspace.id,
        agent_id=agent.id,
        conversation_id=conversation.id,
    )


async def _create_second_conversation_context(
    session_factory: async_sessionmaker[AsyncSession],
    context: PlanningRuntimeContext,
) -> PlanningRuntimeContext:
    async with session_factory() as db:
        conversation = Conversation(
            user_id=context.user_id,
            workspace_id=context.workspace_id,
            created_by=context.user_id,
            active_agent_id=context.agent_id,
        )
        db.add(conversation)
        await db.commit()

    return PlanningRuntimeContext(
        user_id=context.user_id,
        workspace_id=context.workspace_id,
        agent_id=context.agent_id,
        conversation_id=conversation.id,
    )


async def _execute_tool_turn(
    session_factory: async_sessionmaker[AsyncSession],
    context: PlanningRuntimeContext,
    *,
    tool_name: str,
    args: dict[str, object],
    final_text: str = "done",
    seen_messages: list[ModelMessage] | None = None,
) -> tuple[ExecuteRunResult, CollectingSink, UUID]:
    async with session_factory() as db:
        run = await create_agent_run(
            db,
            conversation_id=context.conversation_id,
            agent_id=context.agent_id,
            workspace_id=context.workspace_id,
            user_id=context.user_id,
            trigger="interactive",
        )
        await db.commit()

    stream_function = _single_tool_stream(
        tool_name=tool_name,
        args=args,
        final_text=final_text,
        seen_messages=seen_messages,
    )
    sink = CollectingSink(run_id=run.id, conversation_id=context.conversation_id)
    async with session_factory() as db:
        result = await execute_run(
            db,
            conversation_id=context.conversation_id,
            run_id=run.id,
            user_prompt="Use the tool.",
            sink=sink,
            model=FunctionModel(
                stream_function=stream_function,
                model_name=f"{tool_name}-model",
            ),
        )

    assert result.run.status == RUN_STATUS_COMPLETED
    return result, sink, run.id


def _single_tool_stream(
    *,
    tool_name: str,
    args: dict[str, object],
    final_text: str,
    seen_messages: list[ModelMessage] | None,
):
    state = {"called": False}
    captured_messages = seen_messages if seen_messages is not None else []

    async def stream(
        messages: list[ModelMessage],
        _info: AgentInfo,
    ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        captured_messages[:] = messages
        if not state["called"]:
            state["called"] = True
            yield {
                0: DeltaToolCall(
                    name=tool_name,
                    json_args=json.dumps(args),
                    tool_call_id=f"{tool_name}-{uuid4().hex}",
                )
            }
            return
        yield final_text

    return stream


async def _todo_list(
    session_factory: async_sessionmaker[AsyncSession],
    context: PlanningRuntimeContext,
) -> ConversationTodoList | None:
    async with session_factory() as db:
        return await db.scalar(
            select(ConversationTodoList).where(
                ConversationTodoList.conversation_id == context.conversation_id,
                ConversationTodoList.workspace_id == context.workspace_id,
                ConversationTodoList.deleted == False,  # noqa: E712
            )
        )


async def _tool_audit_events(
    session_factory: async_sessionmaker[AsyncSession],
    context: PlanningRuntimeContext,
    *,
    run_id: UUID,
    tool_name: str,
) -> list[AuditEvent]:
    async with session_factory() as db:
        return list(
            (
                await db.scalars(
                    select(AuditEvent)
                    .where(
                        AuditEvent.workspace_id == context.workspace_id,
                        AuditEvent.tool_name == tool_name,
                        AuditEvent.details["run_id"].astext == str(run_id),
                    )
                    .order_by(AuditEvent.occurred_at)
                )
            ).all()
        )


async def _delete_committed_planning_context(
    session_factory: async_sessionmaker[AsyncSession],
    context: PlanningRuntimeContext,
    *,
    delete_shared: bool = True,
) -> None:
    async with session_factory() as db:
        await db.execute(
            delete(AuditEvent).where(AuditEvent.workspace_id == context.workspace_id)
        )
        await db.execute(
            delete(ConversationTodoList).where(
                ConversationTodoList.conversation_id == context.conversation_id
            )
        )
        await db.execute(
            delete(ConversationMessage).where(
                ConversationMessage.conversation_id == context.conversation_id
            )
        )
        await db.execute(
            delete(AgentRun).where(AgentRun.conversation_id == context.conversation_id)
        )
        await db.execute(
            delete(Conversation).where(Conversation.id == context.conversation_id)
        )
        if delete_shared:
            await db.execute(delete(Agent).where(Agent.id == context.agent_id))
            await db.execute(delete(User).where(User.id == context.user_id))
            await db.execute(
                delete(Workspace).where(Workspace.id == context.workspace_id)
            )
        await db.commit()
