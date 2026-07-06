# apps/api/tests/services/agents/runtime/test_runtime_core.py

"""Runtime-core tests for sink/event translation and provider-free execution."""

import asyncio
import importlib
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from pydantic_ai import (
    Agent as PydanticAgent,
    DeferredToolRequests,
    DeferredToolResults,
    ToolApproved,
    ToolDenied,
    UsageLimitExceeded,
)
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelRequest,
    ModelResponse,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    TextPart,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.settings import settings
from models.agent import Agent
from models.agent_run import AgentRun
from models.conversation import Conversation, ConversationMessage
from models.session import Session
from models.user import User
from models.workspace import Workspace, WorkspaceMembership
from services.agent_runs import create_agent_run
from services.agent_runs.domain import (
    RUN_STATUS_AWAITING_APPROVAL,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
)
from services.agents.models.domain import ModelConfigurationError
from services.agents.runtime.approval_events import (
    emit_deferred_tool_resume_events,
    is_deferred_tool_resume_event,
)
from services.agents.runtime.approval_state import (
    APPROVAL_STATE_METADATA_KEY,
    load_suspended_run_state,
)
from services.agents.runtime.events import (
    EVENT_DONE,
    EVENT_ERROR,
    EVENT_MESSAGE_DELTA,
    EVENT_MESSAGE_END,
    EVENT_MESSAGE_START,
    EVENT_RUN_STATUS,
    EVENT_TOOL_APPROVAL_REQUIRED,
    EVENT_TOOL_CALL,
    EVENT_TOOL_RESULT,
    EventTranslationState,
    emit_agent_stream_event,
)
from services.agents.runtime.execute_run import execute_run
from services.agents.runtime.loop import build_runtime_agent
from services.agents.runtime.sinks import CollectingSink, StreamSink
from services.agents.runtime.worker import run_turn_worker
from tests.factories import build_user, build_workspace

pytestmark = pytest.mark.asyncio

execute_run_module = importlib.import_module("services.agents.runtime.execute_run")


@dataclass(frozen=True)
class RuntimeContext:
    user_id: UUID
    workspace_id: UUID
    agent_id: UUID
    conversation_id: UUID
    run_id: UUID


async def test_event_translation_emits_message_and_tool_events() -> None:
    """The stream translator maps Pydantic AI events to the owned runtime contract."""
    agent = PydanticAgent(TestModel(), name="runtime-translator")

    @agent.tool_plain
    def add(a: int, b: int) -> int:
        return a + b

    run_id = uuid4()
    conversation_id = uuid4()
    sink = CollectingSink(run_id=run_id, conversation_id=conversation_id)
    state = EventTranslationState()

    async with agent.run_stream_events("compute something") as stream:
        async for event in stream:
            await emit_agent_stream_event(sink, event, run_id=str(run_id), state=state)

    event_names = [event.event for event in sink.events]
    assert EVENT_TOOL_CALL in event_names
    assert EVENT_TOOL_RESULT in event_names
    assert EVENT_MESSAGE_START in event_names
    assert EVENT_MESSAGE_DELTA in event_names
    assert EVENT_MESSAGE_END in event_names
    assert [event.data["seq"] for event in sink.events] == list(range(1, len(sink.events) + 1))


async def test_event_translation_emits_text_from_part_start() -> None:
    """Some providers include leading text on the initial text part."""
    run_id = uuid4()
    sink = CollectingSink(run_id=run_id, conversation_id=uuid4())
    state = EventTranslationState()

    await emit_agent_stream_event(
        sink,
        PartStartEvent(index=0, part=TextPart(content="hello")),
        run_id=str(run_id),
        state=state,
    )

    assert [event.event for event in sink.events] == [EVENT_MESSAGE_START, EVENT_MESSAGE_DELTA]
    assert sink.events[0].data["channel"] == "text"
    assert sink.events[1].data["text"] == "hello"


async def test_event_translation_emits_thinking_from_part_start_and_delta() -> None:
    """Thinking parts stream over the message channel without leaking signatures."""
    run_id = uuid4()
    sink = CollectingSink(run_id=run_id, conversation_id=uuid4())
    state = EventTranslationState()

    await emit_agent_stream_event(
        sink,
        PartStartEvent(index=0, part=ThinkingPart(content="Let me think")),
        run_id=str(run_id),
        state=state,
    )

    assert [event.event for event in sink.events] == [EVENT_MESSAGE_START, EVENT_MESSAGE_DELTA]
    message_id = sink.events[0].data["message_id"]
    assert sink.events[0].data["channel"] == "thinking"
    assert sink.events[1].data == {
        "run_id": str(run_id),
        "conversation_id": str(sink.conversation_id),
        "seq": 2,
        "message_id": message_id,
        "text": "Let me think",
    }

    await emit_agent_stream_event(
        sink,
        PartDeltaEvent(index=0, delta=ThinkingPartDelta(content_delta=" more")),
        run_id=str(run_id),
        state=state,
    )
    assert sink.events[-1].event == EVENT_MESSAGE_DELTA
    assert sink.events[-1].data["message_id"] == message_id
    assert sink.events[-1].data["text"] == " more"

    event_count = len(sink.events)
    await emit_agent_stream_event(
        sink,
        PartDeltaEvent(
            index=0,
            delta=ThinkingPartDelta(content_delta=None, signature_delta="signature"),
        ),
        run_id=str(run_id),
        state=state,
    )
    assert len(sink.events) == event_count


async def test_event_translation_keeps_interleaved_thinking_and_text_ids_distinct() -> None:
    """Open thinking and text parts can overlap without colliding ids."""
    run_id = uuid4()
    sink = CollectingSink(run_id=run_id, conversation_id=uuid4())
    state = EventTranslationState()
    thinking_part = ThinkingPart(content="Plan")
    text_part = TextPart(content="Answer")

    await emit_agent_stream_event(
        sink,
        PartStartEvent(index=0, part=thinking_part),
        run_id=str(run_id),
        state=state,
    )
    await emit_agent_stream_event(
        sink,
        PartStartEvent(index=1, part=text_part),
        run_id=str(run_id),
        state=state,
    )
    await emit_agent_stream_event(
        sink,
        PartEndEvent(index=0, part=thinking_part),
        run_id=str(run_id),
        state=state,
    )
    await emit_agent_stream_event(
        sink,
        PartEndEvent(index=1, part=text_part),
        run_id=str(run_id),
        state=state,
    )

    start_events = [event for event in sink.events if event.event == EVENT_MESSAGE_START]
    end_events = [event for event in sink.events if event.event == EVENT_MESSAGE_END]

    assert [event.data["channel"] for event in start_events] == ["thinking", "text"]
    assert start_events[0].data["message_id"] != start_events[1].data["message_id"]
    assert [event.data["message_id"] for event in end_events] == [
        start_events[0].data["message_id"],
        start_events[1].data["message_id"],
    ]


async def test_deferred_resume_filter_only_suppresses_deferred_tool_ids() -> None:
    """Fresh post-resume tool calls should keep using normal stream translation."""
    deferred_tool_call_id = "deferred-tool-call"
    fresh_tool_call_id = "fresh-tool-call"
    deferred_tool_call_ids = {deferred_tool_call_id}

    assert is_deferred_tool_resume_event(
        FunctionToolCallEvent(
            part=ToolCallPart(
                tool_name="approved_tool",
                args={"value": 1},
                tool_call_id=deferred_tool_call_id,
            )
        ),
        deferred_tool_call_ids=deferred_tool_call_ids,
    )
    assert is_deferred_tool_resume_event(
        FunctionToolResultEvent(
            part=ToolReturnPart(
                tool_name="approved_tool",
                content="approved",
                tool_call_id=deferred_tool_call_id,
            )
        ),
        deferred_tool_call_ids=deferred_tool_call_ids,
    )
    assert not is_deferred_tool_resume_event(
        FunctionToolCallEvent(
            part=ToolCallPart(
                tool_name="fresh_tool",
                args={"value": 2},
                tool_call_id=fresh_tool_call_id,
            )
        ),
        deferred_tool_call_ids=deferred_tool_call_ids,
    )
    assert not is_deferred_tool_resume_event(
        FunctionToolResultEvent(
            part=ToolReturnPart(
                tool_name="fresh_tool",
                content="fresh",
                tool_call_id=fresh_tool_call_id,
            )
        ),
        deferred_tool_call_ids=deferred_tool_call_ids,
    )


async def test_deferred_resume_replay_only_replays_deferred_tool_results() -> None:
    """New tool results produced after resume should not become orphan replay events."""
    deferred_tool_call_id = "deferred-tool-call"
    fresh_tool_call_id = "fresh-tool-call"
    sink = CollectingSink(run_id=uuid4(), conversation_id=uuid4())

    await emit_deferred_tool_resume_events(
        sink,
        message_history=[
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="approved_tool",
                        args={"value": 1},
                        tool_call_id=deferred_tool_call_id,
                    )
                ]
            )
        ],
        new_messages=[
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="approved_tool",
                        content="approved",
                        tool_call_id=deferred_tool_call_id,
                    )
                ]
            ),
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="fresh_tool",
                        args={"value": 2},
                        tool_call_id=fresh_tool_call_id,
                    )
                ]
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="fresh_tool",
                        content="fresh",
                        tool_call_id=fresh_tool_call_id,
                    )
                ]
            ),
        ],
        deferred_tool_results=DeferredToolResults(
            approvals={deferred_tool_call_id: ToolApproved(override_args={"value": 10})}
        ),
    )

    assert [(event.event, event.data["tool_call_id"]) for event in sink.events] == [
        (EVENT_TOOL_CALL, deferred_tool_call_id),
        (EVENT_TOOL_RESULT, deferred_tool_call_id),
    ]
    assert sink.events[0].data["args"] == {"value": 10}
    assert sink.events[1].data["result"] == "approved"


@pytest_asyncio.fixture
async def runtime_context(db_session: AsyncSession) -> RuntimeContext:
    user = build_user(email=f"runtime-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"runtime-{uuid4().hex[:8]}")
    db_session.add_all([user, workspace])
    await db_session.flush()

    agent = Agent(
        name="Runtime Agent",
        slug=f"runtime-agent-{uuid4().hex[:8]}",
        instructions="Reply plainly.",
        workspace_id=workspace.id,
        created_by=user.id,
        model_provider="openai",
        model="gpt-5.4-mini",
    )
    db_session.add(agent)
    await db_session.flush()

    conversation = Conversation(
        user_id=user.id,
        workspace_id=workspace.id,
        created_by=user.id,
        active_agent_id=agent.id,
    )
    db_session.add(conversation)
    await db_session.flush()

    run = await create_agent_run(
        db_session,
        conversation_id=conversation.id,
        agent_id=agent.id,
        workspace_id=workspace.id,
        user_id=user.id,
        trigger="interactive",
    )

    return RuntimeContext(
        user_id=user.id,
        workspace_id=workspace.id,
        agent_id=agent.id,
        conversation_id=conversation.id,
        run_id=run.id,
    )


async def test_execute_run_persists_messages_usage_and_events(
    db_session: AsyncSession,
    runtime_context: RuntimeContext,
) -> None:
    agent = await db_session.get(Agent, runtime_context.agent_id)
    assert agent is not None
    assert (
        build_runtime_agent(
            agent,
            model=TestModel(),
        ).usage_limits.total_tokens_limit
        is None
    )

    sink = CollectingSink(
        run_id=runtime_context.run_id,
        conversation_id=runtime_context.conversation_id,
    )

    result = await execute_run(
        db_session,
        conversation_id=runtime_context.conversation_id,
        run_id=runtime_context.run_id,
        user_prompt="Hello",
        sink=sink,
        model=TestModel(call_tools=[]),
    )

    assert result.output == "success (no tool calls)"
    assert result.new_message_count == 2
    assert result.run.status == RUN_STATUS_COMPLETED
    assert result.run.model_name == "openai:gpt-5.4-mini"
    assert result.run.requests == 1
    assert result.run.output_tokens is not None

    messages = (
        await db_session.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == runtime_context.conversation_id)
            .order_by(ConversationMessage.sequence)
        )
    ).all()
    assert [message.sequence for message in messages] == [1, 2]
    assert [message.role for message in messages] == ["user", "assistant"]
    assert all(message.metadata_json["source"] == "pydantic_ai" for message in messages)
    assert messages[0].parts["kind"] == "request"
    assert messages[1].parts["kind"] == "response"

    stored_run = await db_session.get(AgentRun, runtime_context.run_id)
    assert stored_run is not None
    assert stored_run.status == RUN_STATUS_COMPLETED

    event_names = [event.event for event in sink.events]
    assert event_names[0] == EVENT_RUN_STATUS
    assert EVENT_MESSAGE_DELTA in event_names
    assert event_names[-2:] == [EVENT_RUN_STATUS, EVENT_DONE]
    assert _joined_message_deltas(sink) == result.output


async def test_execute_run_streams_message_delta_before_model_completes(
    db_session: AsyncSession,
    runtime_context: RuntimeContext,
) -> None:
    """Live sinks must receive text deltas before the model run reaches completion."""
    release_stream = asyncio.Event()
    sink = StreamSink(
        run_id=runtime_context.run_id,
        conversation_id=runtime_context.conversation_id,
    )

    async def delayed_stream(_messages, _agent_info):
        yield "first "
        await release_stream.wait()
        yield "second"

    task = asyncio.create_task(
        execute_run(
            db_session,
            conversation_id=runtime_context.conversation_id,
            run_id=runtime_context.run_id,
            user_prompt="Hello",
            sink=sink,
            model=FunctionModel(
                stream_function=delayed_stream,
                model_name="delayed-stream",
            ),
        )
    )

    try:
        while True:
            frame = await asyncio.wait_for(sink.next_frame(), timeout=1)
            assert frame is not None
            if f"event: {EVENT_MESSAGE_DELTA}" in frame:
                assert '"text":"first "' in frame
                assert not task.done()
                break

        release_stream.set()
        result = await asyncio.wait_for(task, timeout=2)
        assert result.output == "first second"
    finally:
        release_stream.set()
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


async def test_execute_run_suspends_when_tool_requires_approval(
    db_session: AsyncSession,
    runtime_context: RuntimeContext,
) -> None:
    await _configure_agent_tools(
        db_session,
        agent_id=runtime_context.agent_id,
        tool_names=["test_add_numbers"],
        tool_policies={"test_add_numbers": "approval"},
    )
    sink = CollectingSink(
        run_id=runtime_context.run_id,
        conversation_id=runtime_context.conversation_id,
    )

    result = await execute_run(
        db_session,
        conversation_id=runtime_context.conversation_id,
        run_id=runtime_context.run_id,
        user_prompt="Add two numbers",
        sink=sink,
        model=TestModel(call_tools=["test_add_numbers"]),
        client_message_id="approval-client",
    )

    assert isinstance(result.output, DeferredToolRequests)
    assert result.run.status == RUN_STATUS_AWAITING_APPROVAL
    assert result.new_message_count == 2

    stored_run = await db_session.get(AgentRun, runtime_context.run_id)
    assert stored_run is not None
    assert stored_run.status == RUN_STATUS_AWAITING_APPROVAL
    assert stored_run.lease_expires_at is None
    assert APPROVAL_STATE_METADATA_KEY in (stored_run.metadata_json or {})

    suspended_state = load_suspended_run_state(stored_run)
    assert suspended_state.pending_tool_call_ids == [result.output.approvals[0].tool_call_id]

    messages = (
        await db_session.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == runtime_context.conversation_id)
            .order_by(ConversationMessage.sequence)
        )
    ).all()
    assert [message.role for message in messages] == ["user", "assistant"]
    assert messages[0].client_message_id == "approval-client"

    event_names = [event.event for event in sink.events]
    assert EVENT_TOOL_CALL in event_names
    assert EVENT_TOOL_APPROVAL_REQUIRED in event_names
    assert event_names[-2:] == [EVENT_RUN_STATUS, EVENT_DONE]
    assert sink.events[-2].data["status"] == RUN_STATUS_AWAITING_APPROVAL
    assert sink.events[-1].data["status"] == RUN_STATUS_AWAITING_APPROVAL


async def test_execute_run_resumes_approved_tool_and_clears_approval_state(
    db_session: AsyncSession,
    runtime_context: RuntimeContext,
) -> None:
    await _configure_agent_tools(
        db_session,
        agent_id=runtime_context.agent_id,
        tool_names=["test_add_numbers"],
        tool_policies={"test_add_numbers": "approval"},
    )
    suspended = await execute_run(
        db_session,
        conversation_id=runtime_context.conversation_id,
        run_id=runtime_context.run_id,
        user_prompt="Add two numbers",
        sink=CollectingSink(
            run_id=runtime_context.run_id,
            conversation_id=runtime_context.conversation_id,
        ),
        model=TestModel(call_tools=["test_add_numbers"]),
    )
    assert isinstance(suspended.output, DeferredToolRequests)

    stored_run = await db_session.get(AgentRun, runtime_context.run_id)
    assert stored_run is not None
    suspended_state = load_suspended_run_state(stored_run)
    tool_call_id = suspended_state.pending_tool_call_ids[0]
    resume_sink = CollectingSink(
        run_id=runtime_context.run_id,
        conversation_id=runtime_context.conversation_id,
    )

    resumed = await execute_run(
        db_session,
        conversation_id=runtime_context.conversation_id,
        run_id=runtime_context.run_id,
        user_prompt=None,
        sink=resume_sink,
        model=TestModel(call_tools=["test_add_numbers"]),
        expected_status=RUN_STATUS_AWAITING_APPROVAL,
        message_history=suspended_state.message_history,
        deferred_tool_results=DeferredToolResults(
            approvals={tool_call_id: ToolApproved(override_args={"a": 2, "b": 3})}
        ),
    )

    assert resumed.run.status == RUN_STATUS_COMPLETED
    assert not isinstance(resumed.output, DeferredToolRequests)
    assert "5" in str(resumed.output)
    assert resumed.new_message_count == 2
    stored_run = await db_session.get(AgentRun, runtime_context.run_id)
    assert stored_run is not None
    assert stored_run.status == RUN_STATUS_COMPLETED
    assert APPROVAL_STATE_METADATA_KEY not in (stored_run.metadata_json or {})

    messages = (
        await db_session.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == runtime_context.conversation_id)
            .order_by(ConversationMessage.sequence)
        )
    ).all()
    assert [message.role for message in messages] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    approval_results = (messages[2].metadata_json or {}).get("approval_results")
    assert approval_results == {
        tool_call_id: {
            "decision": "approved",
            "effective_args": {"a": 2, "b": 3},
            "original_args": {"a": 0, "b": 0},
            "override_args": {"a": 2, "b": 3},
        }
    }
    assert [event.event for event in resume_sink.events][-2:] == [
        EVENT_RUN_STATUS,
        EVENT_DONE,
    ]
    resume_event_names = [event.event for event in resume_sink.events]
    assert EVENT_TOOL_CALL in resume_event_names
    assert EVENT_TOOL_RESULT in resume_event_names
    tool_result_events = [event for event in resume_sink.events if event.event == EVENT_TOOL_RESULT]
    tool_call_events = [event for event in resume_sink.events if event.event == EVENT_TOOL_CALL]
    assert tool_call_events[0].data["args"] == {"a": 2, "b": 3}
    assert tool_result_events[0].data["tool_call_id"] == tool_call_id
    assert tool_result_events[0].data["name"] == "test_add_numbers"
    assert tool_result_events[0].data["result"] == 5


async def test_execute_run_resumes_denied_tool_with_typed_denial(
    db_session: AsyncSession,
    runtime_context: RuntimeContext,
) -> None:
    await _configure_agent_tools(
        db_session,
        agent_id=runtime_context.agent_id,
        tool_names=["test_add_numbers"],
        tool_policies={"test_add_numbers": "approval"},
    )
    suspended = await execute_run(
        db_session,
        conversation_id=runtime_context.conversation_id,
        run_id=runtime_context.run_id,
        user_prompt="Add two numbers",
        sink=CollectingSink(
            run_id=runtime_context.run_id,
            conversation_id=runtime_context.conversation_id,
        ),
        model=TestModel(call_tools=["test_add_numbers"]),
    )
    assert isinstance(suspended.output, DeferredToolRequests)

    stored_run = await db_session.get(AgentRun, runtime_context.run_id)
    assert stored_run is not None
    suspended_state = load_suspended_run_state(stored_run)
    tool_call_id = suspended_state.pending_tool_call_ids[0]

    resumed = await execute_run(
        db_session,
        conversation_id=runtime_context.conversation_id,
        run_id=runtime_context.run_id,
        user_prompt=None,
        sink=CollectingSink(
            run_id=runtime_context.run_id,
            conversation_id=runtime_context.conversation_id,
        ),
        model=TestModel(call_tools=["test_add_numbers"]),
        expected_status=RUN_STATUS_AWAITING_APPROVAL,
        message_history=suspended_state.message_history,
        deferred_tool_results=DeferredToolResults(
            approvals={tool_call_id: ToolDenied("Denied by test")}
        ),
    )

    assert resumed.run.status == RUN_STATUS_COMPLETED
    assert not isinstance(resumed.output, DeferredToolRequests)

    messages = (
        await db_session.scalars(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == runtime_context.conversation_id)
            .order_by(ConversationMessage.sequence)
        )
    ).all()
    tool_messages = [message for message in messages if message.role == "tool"]
    assert tool_messages
    assert "Denied by test" in str(tool_messages[0].parts)
    approval_results = (tool_messages[0].metadata_json or {}).get("approval_results")
    assert approval_results == {
        tool_call_id: {
            "decision": "denied",
            "effective_args": {"a": 0, "b": 0},
            "message": "Denied by test",
            "original_args": {"a": 0, "b": 0},
        }
    }


async def test_execute_run_has_no_open_transaction_while_streaming(
    db_session: AsyncSession,
    runtime_context: RuntimeContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream_entered = asyncio.Event()
    release_stream = asyncio.Event()
    sink = CollectingSink(
        run_id=runtime_context.run_id,
        conversation_id=runtime_context.conversation_id,
    )

    class BlockingStream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _traceback) -> bool:
            return False

        def __aiter__(self):
            return self

        async def __anext__(self):
            stream_entered.set()
            await release_stream.wait()
            raise StopAsyncIteration

    class BlockingAgent:
        def run_stream_events(self, *_args, **_kwargs) -> BlockingStream:
            return BlockingStream()

    fake_runtime_agent = SimpleNamespace(
        agent=BlockingAgent(),
        resolved_model=SimpleNamespace(qualified_id="openai:gpt-5.4-mini"),
        usage_limits=None,
    )
    monkeypatch.setattr(
        execute_run_module,
        "build_runtime_agent",
        lambda _agent, **_kwargs: fake_runtime_agent,
    )

    task = asyncio.create_task(
        execute_run(
            db_session,
            conversation_id=runtime_context.conversation_id,
            run_id=runtime_context.run_id,
            user_prompt="Hello",
            sink=sink,
        )
    )

    await asyncio.wait_for(stream_entered.wait(), timeout=1)
    assert not db_session.in_transaction()

    release_stream.set()
    with pytest.raises(RuntimeError, match="stream ended without a terminal result"):
        await task


async def test_execute_run_commits_failed_status_before_reraising(
    db_session: AsyncSession,
    runtime_context: RuntimeContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)
    sink = CollectingSink(
        run_id=runtime_context.run_id,
        conversation_id=runtime_context.conversation_id,
    )

    with pytest.raises(ModelConfigurationError):
        await execute_run(
            db_session,
            conversation_id=runtime_context.conversation_id,
            run_id=runtime_context.run_id,
            user_prompt="Hello",
            sink=sink,
        )
    await db_session.rollback()

    stored_run = await db_session.get(AgentRun, runtime_context.run_id)
    assert stored_run is not None
    assert stored_run.status == RUN_STATUS_FAILED
    assert stored_run.started_at is not None
    assert stored_run.failed_at is not None
    assert stored_run.error_code == "ModelConfigurationError"
    assert "Missing credential" in (stored_run.error_message or "")

    event_names = [event.event for event in sink.events]
    assert event_names == [EVENT_RUN_STATUS, EVENT_RUN_STATUS, EVENT_ERROR, EVENT_DONE]
    assert sink.events[-1].data["status"] == RUN_STATUS_FAILED


async def test_execute_run_total_token_limit_fails_cleanly(
    db_session: AsyncSession,
    runtime_context: RuntimeContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AGENT_RUN_TOTAL_TOKENS_LIMIT", 1)
    sink = CollectingSink(
        run_id=runtime_context.run_id,
        conversation_id=runtime_context.conversation_id,
    )

    with pytest.raises(UsageLimitExceeded):
        await execute_run(
            db_session,
            conversation_id=runtime_context.conversation_id,
            run_id=runtime_context.run_id,
            user_prompt="Hello",
            sink=sink,
            model=TestModel(call_tools=[]),
        )
    await db_session.rollback()

    stored_run = await db_session.get(AgentRun, runtime_context.run_id)
    assert stored_run is not None
    assert stored_run.status == RUN_STATUS_FAILED
    assert stored_run.error_code == "UsageLimitExceeded"

    event_names = [event.event for event in sink.events]
    assert event_names[-2:] == [EVENT_ERROR, EVENT_DONE]
    assert sink.events[-2].data["code"] == "UsageLimitExceeded"
    assert sink.events[-1].data["status"] == RUN_STATUS_FAILED


async def test_worker_renews_lease_during_turn_longer_than_original_ttl(
    committed_db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AGENT_RUN_LEASE_TTL_SECONDS", 1)
    monkeypatch.setattr(settings, "AGENT_RUN_HEARTBEAT_INTERVAL_SECONDS", 0.1)

    runtime_context = await _create_committed_runtime_context(committed_db_session_factory)
    stream_entered = asyncio.Event()
    release_stream = asyncio.Event()
    sink = CollectingSink(
        run_id=runtime_context.run_id,
        conversation_id=runtime_context.conversation_id,
    )

    async def delayed_stream(_messages, _agent_info):
        stream_entered.set()
        await release_stream.wait()
        yield "durable reply"

    task = asyncio.create_task(
        run_turn_worker(
            run_id=runtime_context.run_id,
            conversation_id=runtime_context.conversation_id,
            user_prompt="Hello",
            sink=sink,
            model=FunctionModel(stream_function=delayed_stream, model_name="delayed"),
            client_message_id="lease-test",
        )
    )

    try:
        await asyncio.wait_for(stream_entered.wait(), timeout=2)
        await asyncio.sleep(1.25)

        async with committed_db_session_factory() as db:
            run = await db.get(AgentRun, runtime_context.run_id)
            assert run is not None
            assert run.status == "running"
            assert run.lease_expires_at is not None
            assert run.lease_expires_at > datetime.now(UTC)

        release_stream.set()
        await asyncio.wait_for(task, timeout=3)

        async with committed_db_session_factory() as db:
            run = await db.get(AgentRun, runtime_context.run_id)
            assert run is not None
            assert run.status == RUN_STATUS_COMPLETED
            assert run.lease_expires_at is None

            messages = (
                await db.scalars(
                    select(ConversationMessage)
                    .where(ConversationMessage.conversation_id == runtime_context.conversation_id)
                    .order_by(ConversationMessage.sequence)
                )
            ).all()
            assert [message.role for message in messages] == ["user", "assistant"]
            assert messages[0].client_message_id == "lease-test"
    finally:
        release_stream.set()
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await _delete_committed_runtime_context(committed_db_session_factory, runtime_context)


def _joined_message_deltas(sink: CollectingSink) -> str:
    return "".join(
        event.data["text"] for event in sink.events if event.event == EVENT_MESSAGE_DELTA
    )


async def _configure_agent_tools(
    db: AsyncSession,
    *,
    agent_id: UUID,
    tool_names: list[str],
    tool_policies: dict[str, str] | None = None,
) -> None:
    agent = await db.get(Agent, agent_id)
    assert agent is not None
    agent.tool_names = tool_names
    agent.tool_policies = tool_policies
    await db.flush()


async def _create_committed_runtime_context(
    session_factory: async_sessionmaker[AsyncSession],
) -> RuntimeContext:
    async with session_factory() as db:
        user = build_user(email=f"runtime-committed-{uuid4().hex}@example.com")
        workspace = build_workspace(slug=f"runtime-committed-{uuid4().hex[:8]}")
        db.add_all([user, workspace])
        await db.flush()

        agent = Agent(
            name="Committed Runtime Agent",
            slug=f"committed-runtime-agent-{uuid4().hex[:8]}",
            instructions="Reply plainly.",
            workspace_id=workspace.id,
            created_by=user.id,
            model_provider="openai",
            model="gpt-5.4-mini",
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
        await db.flush()

        run = await create_agent_run(
            db,
            conversation_id=conversation.id,
            agent_id=agent.id,
            workspace_id=workspace.id,
            user_id=user.id,
            trigger="interactive",
        )
        await db.commit()

    return RuntimeContext(
        user_id=user.id,
        workspace_id=workspace.id,
        agent_id=agent.id,
        conversation_id=conversation.id,
        run_id=run.id,
    )


async def _delete_committed_runtime_context(
    session_factory: async_sessionmaker[AsyncSession],
    context: RuntimeContext,
) -> None:
    async with session_factory() as db:
        await db.execute(
            delete(ConversationMessage).where(
                ConversationMessage.conversation_id == context.conversation_id
            )
        )
        await db.execute(
            delete(AgentRun).where(AgentRun.conversation_id == context.conversation_id)
        )
        await db.execute(delete(Conversation).where(Conversation.id == context.conversation_id))
        await db.execute(delete(Agent).where(Agent.id == context.agent_id))
        await db.execute(
            delete(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == context.workspace_id
            )
        )
        await db.execute(delete(Session).where(Session.user_id == context.user_id))
        await db.execute(
            update(User).where(User.id == context.user_id).values(default_workspace_id=None)
        )
        await db.execute(delete(User).where(User.id == context.user_id))
        await db.execute(delete(Workspace).where(Workspace.id == context.workspace_id))
        await db.commit()
