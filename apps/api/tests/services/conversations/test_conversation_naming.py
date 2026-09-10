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
from services.conversations.get_conversation import get_conversation
from services.conversations.list_conversations import list_conversations
from services.conversations.mark_read import mark_conversation_read
from services.conversations.naming import (
    ConversationTitle,
    _persist_title_update,
    fallback_conversation_title,
    generate_conversation_title,
)
from tests.factories import build_user, build_workspace, build_workspace_membership


@pytest.fixture(autouse=True)
def _isolate_helper_metering(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_record(_event) -> bool:
        return True

    monkeypatch.setattr(
        "services.ai_usage.run_metered_helper.record_ai_usage_durable",
        fake_record,
    )


@pytest.mark.asyncio
async def test_generate_conversation_title_uses_structured_output() -> None:
    workspace_id, user_id, conversation_id = uuid4(), uuid4(), uuid4()

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
        workspace_id=workspace_id,
        user_id=user_id,
        conversation_id=conversation_id,
        model=FunctionModel(title_function, model_name="title-test"),
    )

    assert title.title == "Quarterly roadmap planning"
    assert title.source == "model"
    assert title.model_name == "title-test"


@pytest.mark.asyncio
async def test_generate_conversation_title_falls_back_when_model_returns_blank() -> None:
    workspace_id, user_id, conversation_id = uuid4(), uuid4(), uuid4()

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
        workspace_id=workspace_id,
        user_id=user_id,
        conversation_id=conversation_id,
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
@pytest.mark.parametrize(
    "personal,source,visibility",
    [
        (False, "direct", "private"),
        (False, "direct", "workspace"),
        (True, "direct", "private"),
        (False, "delegated", "private"),
    ],
)
async def test_persist_title_update_refreshes_conversation_before_emit(
    db_session: AsyncSession,
    personal: bool,
    source: str,
    visibility: str,
) -> None:
    user = build_user(email=f"title-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"title-{uuid4().hex[:8]}", is_personal=personal)
    membership = build_workspace_membership(workspace_id=workspace.id, user_id=user.id)
    conversation = Conversation(
        user_id=user.id,
        workspace_id=workspace.id,
        created_by=user.id,
        title="Fallback title",
        source=source,
        visibility=visibility,
    )
    db_session.add_all([user, workspace, membership, conversation])
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

    expected = {
        "can_reply": source != "delegated",
        "can_manage_sharing": not personal and source != "delegated",
        "can_stop_sharing": visibility == "workspace",
    }
    assert event.data["conversation"]["capabilities"] == expected
    detail = await get_conversation(
        db_session, actor=user, workspace=workspace, conversation_id=conversation.id
    )
    marked = await mark_conversation_read(
        db_session, actor=user, workspace=workspace, conversation_id=conversation.id
    )
    assert detail.capabilities.model_dump() == marked.capabilities.model_dump() == expected
    if source != "delegated":
        listing = await list_conversations(
            db_session, actor=user, workspace=workspace, limit=10, offset=0
        )
        assert listing.conversations[0].capabilities.model_dump() == expected
