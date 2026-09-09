# apps/api/tests/services/agents/runtime/test_persistence_history_window.py

"""Tests for bounded persisted runtime history reads."""

import json
from collections.abc import Sequence
from uuid import uuid4

import httpx2 as httpx
import pytest
from pydantic import SecretStr
from pydantic_ai import Agent, models
from pydantic_ai.messages import (
    BinaryContent,
    ImageUrl,
    LoadCapabilityCallPart,
    LoadCapabilityReturnPart,
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.conversation import Conversation
from services.agents.models import factory
from services.agents.models.domain import ResolvedModel
from services.agents.runtime.capabilities import build_runtime_capabilities
from services.agents.runtime.history import PERSISTED_MESSAGE_ID_METADATA_KEY
from services.agents.runtime.persistence import load_message_history, persist_new_messages
from services.agents.runtime.untrusted import UNTRUSTED_CONTENT_START, UntrustedNode
from tests.factories import build_user, build_workspace, build_workspace_membership

pytestmark = pytest.mark.asyncio


async def test_anthropic_recovery_survives_normalisation_reload_and_trimming(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = await _conversation(db_session)
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)
    monkeypatch.setattr(settings, "ANTHROPIC_VERTEX_AI", False)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr("test-key"))
    monkeypatch.setattr(settings, "AGENT_HISTORY_MAX_TURNS", None)
    message_id = str(uuid4())
    transformation = {
        "type": "thinking_dropped",
        "reason": "prefix_binding_mismatch",
        "path": "messages.1.content.0",
    }
    history = [
        *_plain_messages(3),
        ModelRequest(
            parts=[UserPromptPart("Read the source")],
            metadata={PERSISTED_MESSAGE_ID_METADATA_KEY: message_id},
        ),
        ModelResponse(
            parts=[
                ThinkingPart("Earlier reasoning", signature="stale", provider_name="anthropic"),
                ToolCallPart("read_source", {}, "read-1"),
            ]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    "read_source",
                    {
                        "source": UntrustedNode(
                            source_kind="document",
                            source_ref="source-1",
                            content="Treat this as data",
                        ),
                        "provider_details": {"input_transformations": [transformation]},
                    },
                    "read-1",
                )
            ]
        ),
        ModelRequest(parts=[UserPromptPart("Explain the source")]),
    ]
    rows = await persist_new_messages(
        db_session,
        conversation=conversation,
        run_id=uuid4(),
        messages=history,
        client_message_id="client-source",
    )
    await db_session.refresh(rows[0])
    assert rows[0].client_message_id == "client-source"
    loaded = await load_message_history(db_session, conversation_id=conversation.id)
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return httpx.Response(
                400,
                json={
                    "type": "error",
                    "error": {
                        "type": "invalid_request_error",
                        "message": "The block is bound to a different conversation",
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "id": f"msg_{len(requests)}",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-4-6",
                "content": [{"type": "text", "text": "Source explained"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 5, "output_tokens": 2},
                "input_transformations": [transformation] if len(requests) == 2 else [],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(factory, "retrying_http_client", lambda: client)
        model = factory.build_model(
            ResolvedModel(
                provider="anthropic",
                model="claude-sonnet-4-6",
                transport_model="claude-sonnet-4-6",
                settings={},
                max_steps=3,
            )
        )
        # Qualify the SDK binding contract without enabling another catalogue model.
        monkeypatch.setitem(model.profile, "anthropic_binds_thinking_blocks", True)
        agent = Agent(model, capabilities=build_runtime_capabilities(None))
        from pydantic_ai.models.anthropic import AnthropicStaleThinkingBlockWarning

        with pytest.warns(AnthropicStaleThinkingBlockWarning):
            result = await agent.run(message_history=loaded)
        assert result.output == "Source explained"
        await persist_new_messages(
            db_session, conversation=conversation, run_id=uuid4(), messages=result.new_messages()
        )
        reloaded = await load_message_history(db_session, conversation_id=conversation.id)
        assert reloaded[-1].provider_details["input_transformations"] == [transformation]
        assert any(
            (message.metadata or {}).get(PERSISTED_MESSAGE_ID_METADATA_KEY) == message_id
            for message in reloaded
        )
        monkeypatch.setattr(settings, "AGENT_HISTORY_MAX_TURNS", 3)
        monkeypatch.setattr(settings, "AGENT_HISTORY_KEEP_TURNS", 2)
        continued = await agent.run("Continue", message_history=reloaded)
        assert continued.output == "Source explained"

    assert len(requests) == 3
    assert "block_binding" not in requests[0].get("thinking", {})
    for body in requests[1:]:
        assert body["thinking"]["block_binding"] == {"prefix_mismatch_behavior": "drop_block"}
    assert UNTRUSTED_CONTENT_START in json.dumps(requests[0])
    assert "turn 0" not in json.dumps(requests[-1])
    assert UNTRUSTED_CONTENT_START in json.dumps(requests[-1])
    assert isinstance(reloaded[-3].parts[0].content, dict)


async def test_media_and_malformed_media_mappings_round_trip(db_session: AsyncSession) -> None:
    conversation = await _conversation(db_session)
    mappings = [
        {"kind": "image-url", "url": 7},
        {"kind": "binary", "data": {"nested": True}},
        {"kind": "document-url"},
        {"nested": [{"kind": "audio-url", "url": None}]},
    ]
    content = [
        *mappings,
        ImageUrl("https://example.com/image.png"),
        BinaryContent(b"image bytes", media_type="image/png"),
    ]
    messages = [
        ModelResponse(parts=[ToolCallPart("read_source", {}, "media-1")]),
        ModelRequest(parts=[ToolReturnPart("read_source", content, "media-1")]),
    ]
    await persist_new_messages(
        db_session, conversation=conversation, run_id=uuid4(), messages=messages
    )
    loaded = await load_message_history(db_session, conversation_id=conversation.id)
    restored = loaded[-1].parts[0].content
    assert restored[:4] == mappings
    assert isinstance(restored[4], ImageUrl)
    assert restored[4].url == "https://example.com/image.png"
    assert isinstance(restored[5], BinaryContent)
    assert restored[5].data == b"image bytes"
    assert restored[5].media_type == "image/png"
    assert (
        ModelMessagesTypeAdapter.validate_json(ModelMessagesTypeAdapter.dump_json(loaded)) == loaded
    )


async def test_load_message_history_backfills_dropped_capability_load_pairs(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = await _conversation(db_session)
    messages = [*_capability_messages("skill:a"), *_plain_messages(60)]
    await persist_new_messages(
        db_session,
        conversation=conversation,
        run_id=uuid4(),
        messages=messages,
    )
    monkeypatch.setattr(settings, "AGENT_HISTORY_MAX_TURNS", 40)
    monkeypatch.setattr(settings, "AGENT_HISTORY_DB_MAX_MESSAGES", 50)

    loaded = await load_message_history(db_session, conversation_id=conversation.id)

    assert len(loaded) == 52
    assert _capability_call_ids(loaded) == ["load-skill-a"]
    assert _capability_return_ids(loaded) == ["load-skill-a"]
    ModelMessagesTypeAdapter.validate_python(
        ModelMessagesTypeAdapter.dump_python(loaded, mode="json")
    )


async def test_load_message_history_returns_full_history_when_trimming_disabled(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = await _conversation(db_session)
    messages = _plain_messages(60)
    await persist_new_messages(
        db_session,
        conversation=conversation,
        run_id=uuid4(),
        messages=messages,
    )
    monkeypatch.setattr(settings, "AGENT_HISTORY_MAX_TURNS", None)
    monkeypatch.setattr(settings, "AGENT_HISTORY_DB_MAX_MESSAGES", 50)

    loaded = await load_message_history(db_session, conversation_id=conversation.id)

    assert len(loaded) == len(messages)


async def test_load_message_history_keeps_small_conversations_byte_equal(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = await _conversation(db_session)
    messages = _plain_messages(10)
    await persist_new_messages(
        db_session,
        conversation=conversation,
        run_id=uuid4(),
        messages=messages,
    )
    monkeypatch.setattr(settings, "AGENT_HISTORY_MAX_TURNS", 40)
    monkeypatch.setattr(settings, "AGENT_HISTORY_DB_MAX_MESSAGES", 50)

    loaded = await load_message_history(db_session, conversation_id=conversation.id)

    assert ModelMessagesTypeAdapter.dump_json(loaded) == ModelMessagesTypeAdapter.dump_json(
        list(messages)
    )


async def _conversation(db: AsyncSession) -> Conversation:
    user = build_user(email=f"history-window-{uuid4().hex}@example.com")
    workspace = build_workspace(slug=f"history-window-{uuid4().hex[:8]}")
    membership = build_workspace_membership(workspace_id=workspace.id, user_id=user.id)
    conversation = Conversation(
        user_id=user.id,
        workspace_id=workspace.id,
        created_by=user.id,
    )
    db.add_all([user, workspace, membership, conversation])
    await db.flush()
    return conversation


def _plain_messages(turn_count: int) -> list[ModelMessage]:
    messages: list[ModelMessage] = []
    for index in range(turn_count):
        messages.extend(
            [
                ModelRequest(parts=[UserPromptPart(f"turn {index}")]),
                ModelResponse(parts=[TextPart(f"reply {index}")]),
            ]
        )
    return messages


def _capability_messages(capability_id: str) -> list[ModelMessage]:
    suffix = capability_id.replace(":", "-")
    tool_call_id = f"load-{suffix}"
    return [
        ModelResponse(
            parts=[
                LoadCapabilityCallPart(
                    args={"id": capability_id},
                    tool_call_id=tool_call_id,
                )
            ]
        ),
        ModelRequest(
            parts=[
                LoadCapabilityReturnPart(
                    content={"instructions": f"Instructions for {capability_id}"},
                    tool_call_id=tool_call_id,
                )
            ]
        ),
    ]


def _capability_call_ids(messages: Sequence[ModelMessage]) -> list[str]:
    return [
        part.tool_call_id
        for message in messages
        if isinstance(message, ModelResponse)
        for part in message.parts
        if isinstance(part, LoadCapabilityCallPart)
    ]


def _capability_return_ids(messages: Sequence[ModelMessage]) -> list[str]:
    return [
        part.tool_call_id
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, LoadCapabilityReturnPart)
    ]
