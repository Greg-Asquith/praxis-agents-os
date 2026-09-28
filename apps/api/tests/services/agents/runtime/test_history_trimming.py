# apps/api/tests/services/agents/runtime/test_history_trimming.py

"""Tests for cache-stable runtime history trimming and compaction."""

import pytest
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.capabilities import ProcessHistory
from pydantic_ai.messages import (
    LoadCapabilityCallPart,
    LoadCapabilityReturnPart,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import FunctionModel

from core.settings import settings
from services.agents.runtime.history import (
    AUTOMATIC_SUMMARY_PREFIX,
    history_trimmer,
    trim_history,
)

pytestmark = pytest.mark.asyncio


async def test_trim_history_uses_chunk_math_and_preserves_kept_tool_pairs() -> None:
    history = _history(41, tool_turn=25)

    trimmed = trim_history(history, max_turns=40, keep_turns=20)

    assert _boundary_texts(trimmed) == [f"turn {index}" for index in range(20, 41)]
    assert _tool_call_ids(trimmed) == {"tool-25"}
    assert _tool_return_ids(trimmed) == {"tool-25"}


async def test_trim_history_cut_point_is_stable_between_watermarks() -> None:
    first_kept_turns = []
    for turn_count in range(41, 60):
        trimmed = trim_history(_history(turn_count), max_turns=40, keep_turns=20)
        first_kept_turns.append(_boundary_texts(trimmed)[0])

    assert first_kept_turns == ["turn 20"] * 19
    assert _boundary_texts(trim_history(_history(60), max_turns=40, keep_turns=20))[0] == "turn 40"


async def test_trim_history_does_not_cut_at_merged_tool_return_request() -> None:
    history = _history_with_merged_request_at_cut_candidate()

    trimmed = trim_history(history, max_turns=40, keep_turns=20)

    assert _boundary_texts(trimmed)[0] == "turn 20"
    first_message = trimmed[0]
    assert isinstance(first_message, ModelRequest)
    assert all(not isinstance(part, ToolReturnPart) for part in first_message.parts)


async def test_trim_history_preserves_trailing_approval_tool_calls() -> None:
    trailing_response = ModelResponse(
        parts=[
            ToolCallPart(
                tool_name="needs_approval",
                args={"id": "pending"},
                tool_call_id="approval-1",
            )
        ]
    )
    history = [*_history(41), trailing_response]

    trimmed = trim_history(history, max_turns=40, keep_turns=20)

    assert trimmed[-1] is trailing_response
    assert "approval-1" in _tool_call_ids(trimmed)


async def test_trim_history_preserves_dropped_capability_loads_without_duplicates() -> None:
    history = _history_with_capability_loads(
        dropped_ids=["skill:a", "skill:b"],
        kept_ids=["skill:b"],
    )

    trimmed = trim_history(history, max_turns=40, keep_turns=20)

    synthetic_response = trimmed[1]
    synthetic_request = trimmed[2]
    assert isinstance(synthetic_response, ModelResponse)
    assert isinstance(synthetic_request, ModelRequest)
    assert [
        part.capability_id
        for part in synthetic_response.parts
        if isinstance(part, LoadCapabilityCallPart)
    ] == ["skill:a"]
    assert [
        part.tool_call_id
        for part in synthetic_request.parts
        if isinstance(part, LoadCapabilityReturnPart)
    ] == ["load-skill-a"]


async def test_summary_is_injected_once_after_the_kept_boundary() -> None:
    trimmed = trim_history(
        _history(41),
        max_turns=40,
        keep_turns=20,
        summary="The operator chose the amber theme.",
    )

    summary_parts = [
        part
        for message in trimmed
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, UserPromptPart)
        and isinstance(part.content, str)
        and part.content.startswith(AUTOMATIC_SUMMARY_PREFIX)
    ]
    assert len(summary_parts) == 1
    assert summary_parts[0].content.endswith("The operator chose the amber theme.")
    assert _boundary_texts(trimmed)[0] == "turn 20"


async def test_token_pressure_advances_exactly_one_watermark_chunk() -> None:
    normal = trim_history(_history(41), max_turns=40, keep_turns=20)
    pressured = trim_history(
        _history(41),
        max_turns=40,
        keep_turns=20,
        token_pressure=True,
    )

    assert _boundary_texts(normal)[0] == "turn 20"
    assert _boundary_texts(pressured)[0] == "turn 40"


async def test_history_trimmer_does_not_pollute_new_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AGENT_HISTORY_MAX_TURNS", 2)
    monkeypatch.setattr(settings, "AGENT_HISTORY_KEEP_TURNS", 1)
    agent = PydanticAgent(
        FunctionModel(lambda _messages, _info: ModelResponse(parts=[TextPart("ok")])),
        name="history-persistence-test",
        capabilities=[ProcessHistory(history_trimmer())],
    )

    result = await agent.run(
        "current prompt",
        message_history=_history_with_capability_loads(dropped_ids=["skill:a"]),
    )

    assert _load_capability_call_ids(result.all_messages()) == ["load-skill-a"]
    assert _load_capability_call_ids(result.new_messages()) == []
    assert _boundary_texts(result.new_messages()) == ["current prompt"]


def _history(turn_count: int, *, tool_turn: int | None = None) -> list[ModelMessage]:
    messages: list[ModelMessage] = []
    for index in range(turn_count):
        messages.append(_user_request(f"turn {index}"))
        if index == tool_turn:
            messages.extend(
                [
                    ModelResponse(
                        parts=[
                            ToolCallPart(
                                tool_name="lookup",
                                args={"turn": index},
                                tool_call_id=f"tool-{index}",
                            )
                        ]
                    ),
                    ModelRequest(
                        parts=[
                            ToolReturnPart(
                                tool_name="lookup",
                                content={"ok": True},
                                tool_call_id=f"tool-{index}",
                            )
                        ]
                    ),
                ]
            )
        messages.append(ModelResponse(parts=[TextPart(f"reply {index}")]))
    return messages


def _history_with_merged_request_at_cut_candidate() -> list[ModelMessage]:
    messages: list[ModelMessage] = []
    for index in range(20):
        messages.extend(_history_turn(index))
    messages.extend(
        [
            ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="lookup",
                        args={"turn": "merged"},
                        tool_call_id="tool-merged",
                    )
                ]
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(
                        tool_name="lookup",
                        content={"ok": True},
                        tool_call_id="tool-merged",
                    ),
                    UserPromptPart("merged turn"),
                ]
            ),
            ModelResponse(parts=[TextPart("reply merged")]),
        ]
    )
    for index in range(20, 41):
        messages.extend(_history_turn(index))
    return messages


def _history_with_capability_loads(
    *,
    dropped_ids: list[str],
    kept_ids: list[str] | None = None,
) -> list[ModelMessage]:
    messages: list[ModelMessage] = []
    turn_index = 0
    for capability_id in dropped_ids:
        messages.extend(_capability_turn(turn_index, capability_id))
        turn_index += 1
    while turn_index < 20:
        messages.extend(_history_turn(turn_index))
        turn_index += 1
    for turn_index in range(20, 41):
        if kept_ids and turn_index - 20 < len(kept_ids):
            messages.extend(_capability_turn(turn_index, kept_ids[turn_index - 20]))
        else:
            messages.extend(_history_turn(turn_index))
    return messages


def _history_turn(index: int) -> list[ModelMessage]:
    return [_user_request(f"turn {index}"), ModelResponse(parts=[TextPart(f"reply {index}")])]


def _capability_turn(index: int, capability_id: str) -> list[ModelMessage]:
    suffix = capability_id.replace(":", "-")
    tool_call_id = f"load-{suffix}"
    return [
        _user_request(f"turn {index}"),
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
        ModelResponse(parts=[TextPart(f"reply {index}")]),
    ]


def _user_request(content: str) -> ModelRequest:
    return ModelRequest(parts=[UserPromptPart(content)])


def _boundary_texts(messages: list[ModelMessage]) -> list[str]:
    return [
        part.content
        for message in messages
        if isinstance(message, ModelRequest) and _is_clean_boundary(message)
        for part in message.parts
        if isinstance(part, UserPromptPart) and isinstance(part.content, str)
    ]


def _is_clean_boundary(message: ModelRequest) -> bool:
    return any(isinstance(part, UserPromptPart) for part in message.parts) and all(
        not isinstance(part, ToolReturnPart) for part in message.parts
    )


def _tool_call_ids(messages: list[ModelMessage]) -> set[str]:
    return {
        part.tool_call_id
        for message in messages
        if isinstance(message, ModelResponse)
        for part in message.parts
        if isinstance(part, ToolCallPart)
    }


def _tool_return_ids(messages: list[ModelMessage]) -> set[str]:
    return {
        part.tool_call_id
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart)
    }


def _load_capability_call_ids(messages: list[ModelMessage]) -> list[str]:
    return [
        part.tool_call_id
        for message in messages
        if isinstance(message, ModelResponse)
        for part in message.parts
        if isinstance(part, LoadCapabilityCallPart)
    ]
