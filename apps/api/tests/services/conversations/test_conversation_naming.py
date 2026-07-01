# apps/api/tests/services/conversations/test_conversation_naming.py

"""Service tests for structured conversation title generation."""

from uuid import uuid4

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy.ext.asyncio import AsyncSession

from models.conversation import Conversation
from services.agents.runtime.events import EVENT_CONVERSATION_UPDATED
from services.agents.runtime.sinks import CollectingSink
from services.conversations.naming import (
    ConversationTitle,
    _persist_title_update,
    fallback_conversation_title,
    generate_conversation_title,
)
from tests.factories import build_user, build_workspace


@pytest.mark.asyncio
async def test_generate_conversation_title_uses_structured_output() -> None:
    async def title_function(_messages, agent_info: AgentInfo) -> ModelResponse:
        output_tool = agent_info.output_tools[0]
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=output_tool.name,
                    args={"title": '"Quarterly roadmap planning."'},
                    tool_call_id="title-output",
                )
            ]
        )

    title = await generate_conversation_title(
        "Can you help me plan the roadmap for next quarter?",
        model=FunctionModel(title_function, model_name="title-test"),
    )

    assert title.title == "Quarterly roadmap planning"
    assert title.source == "model"
    assert title.model_name == "title-test"


@pytest.mark.asyncio
async def test_generate_conversation_title_falls_back_when_model_returns_blank() -> None:
    async def blank_function(_messages, agent_info: AgentInfo) -> ModelResponse:
        output_tool = agent_info.output_tools[0]
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=output_tool.name,
                    args={"title": "   "},
                    tool_call_id="title-output",
                )
            ]
        )

    title = await generate_conversation_title(
        "Summarize the finance report before tomorrow's board meeting",
        model=FunctionModel(blank_function, model_name="blank-title-test"),
    )

    assert title.title == "Summarize the finance report before tomorrow's board meeting"
    assert title.source == "fallback"
    assert title.model_name == "blank-title-test"


def test_fallback_conversation_title_is_deterministic_and_bounded() -> None:
    prompt = " ".join(["long"] * 40)

    title = fallback_conversation_title(prompt)

    assert title.endswith("...")
    assert len(title) <= 80


@pytest.mark.asyncio
async def test_persist_title_update_refreshes_conversation_before_emit(
    db_session: AsyncSession,
) -> None:
    user = build_user(email=f"title-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"title-{uuid4().hex[:8]}")
    conversation = Conversation(
        user_id=user.id,
        workspace_id=workspace.id,
        created_by=user.id,
        title="Fallback title",
    )
    db_session.add_all([user, workspace, conversation])
    await db_session.commit()

    sink = CollectingSink(run_id=uuid4(), conversation_id=conversation.id)

    await _persist_title_update(
        db_session,
        conversation_id=conversation.id,
        title=ConversationTitle(
            title="Generated title",
            source="model",
            model_name="title-test",
        ),
        fallback_title="Fallback title",
        sink=sink,
    )

    assert len(sink.events) == 1
    event = sink.events[0]
    assert event.event == EVENT_CONVERSATION_UPDATED
    assert event.data["conversation"]["title"] == "Generated title"
    assert event.data["conversation"]["updated_at"] is not None
