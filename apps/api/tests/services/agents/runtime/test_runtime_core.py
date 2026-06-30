# apps/api/tests/services/agents/runtime/test_runtime_core.py

"""Runtime-core tests for sink/event translation and provider-free execution."""

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.messages import PartStartEvent, TextPart
from pydantic_ai.models.test import TestModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.agent import Agent
from models.agent_run import AgentRun
from models.conversation import Conversation, ConversationMessage
from services.agent_runs import create_agent_run
from services.agent_runs.domain import RUN_STATUS_COMPLETED, RUN_STATUS_FAILED
from services.agents.models.domain import ModelConfigurationError
from services.agents.runtime import execute_run
from services.agents.runtime.events import (
    EVENT_DONE,
    EVENT_ERROR,
    EVENT_MESSAGE_DELTA,
    EVENT_MESSAGE_END,
    EVENT_MESSAGE_START,
    EVENT_RUN_STATUS,
    EVENT_TOOL_CALL,
    EVENT_TOOL_RESULT,
    EventTranslationState,
    emit_agent_stream_event,
)
from services.agents.runtime.sinks import CollectingSink
from tests.factories import build_user, build_workspace

pytestmark = pytest.mark.asyncio


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
    assert sink.events[1].data["text"] == "hello"


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
        model=TestModel(),
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
    assert event_names == [EVENT_RUN_STATUS, EVENT_RUN_STATUS, EVENT_ERROR]


def _joined_message_deltas(sink: CollectingSink) -> str:
    return "".join(
        event.data["text"] for event in sink.events if event.event == EVENT_MESSAGE_DELTA
    )
