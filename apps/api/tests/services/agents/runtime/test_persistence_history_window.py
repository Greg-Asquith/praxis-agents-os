# apps/api/tests/services/agents/runtime/test_persistence_history_window.py

"""Tests for bounded persisted runtime history reads."""

from collections.abc import Sequence
from uuid import uuid4

import pytest
from pydantic_ai.messages import (
    LoadCapabilityCallPart,
    LoadCapabilityReturnPart,
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from models.conversation import Conversation
from services.agents.runtime.persistence import load_message_history, persist_new_messages
from tests.factories import build_user, build_workspace, build_workspace_membership

pytestmark = pytest.mark.asyncio


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
