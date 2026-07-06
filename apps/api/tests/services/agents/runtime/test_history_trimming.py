# apps/api/test/services/agents/runtime/test_history_trimming.py

"""Tests for cache-stable runtime history trimming."""

from uuid import uuid4

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
from pydantic_ai.models.function import AgentInfo, FunctionModel

from core.settings import settings
from models.agent import Agent
from services.agents.runtime.history import history_trimmer, trim_history
from services.agents.runtime.loop import _runtime_instructions
from services.agents.runtime.prompt import PLANNING_INSTRUCTIONS
from services.agents.runtime.tools import build_runtime_tools

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


async def test_trim_history_returns_identity_when_under_budget() -> None:
    history = _history(40)

    assert trim_history(history, max_turns=40, keep_turns=20) is history


async def test_trim_history_is_idempotent() -> None:
    trimmed = trim_history(_history(60), max_turns=40, keep_turns=20)

    assert trim_history(trimmed, max_turns=40, keep_turns=20) == trimmed


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


async def test_trim_history_preserves_user_first_with_synthetic_capability_pairs() -> None:
    history = _history_with_capability_loads(dropped_ids=["skill:a"])

    trimmed = trim_history(history, max_turns=40, keep_turns=20)

    first_message = trimmed[0]
    assert isinstance(first_message, ModelRequest)
    assert _is_clean_boundary(first_message)
    assert isinstance(trimmed[1], ModelResponse)
    assert isinstance(trimmed[2], ModelRequest)


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


async def test_history_trimmer_processes_messages_seen_by_function_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[ModelMessage] = []

    def capture(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        seen.clear()
        seen.extend(messages)
        return ModelResponse(parts=[TextPart("ok")])

    monkeypatch.setattr(settings, "AGENT_HISTORY_MAX_TURNS", 2)
    monkeypatch.setattr(settings, "AGENT_HISTORY_KEEP_TURNS", 1)
    agent = PydanticAgent(
        FunctionModel(capture),
        name="history-trim-test",
        capabilities=[ProcessHistory(history_trimmer())],
    )

    await agent.run("current prompt", message_history=_history(3))

    assert _boundary_texts(seen) == ["turn 2", "current prompt"]


async def test_history_trimmer_disabled_sends_full_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[ModelMessage] = []

    def capture(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        seen.clear()
        seen.extend(messages)
        return ModelResponse(parts=[TextPart("ok")])

    monkeypatch.setattr(settings, "AGENT_HISTORY_MAX_TURNS", None)
    agent = PydanticAgent(
        FunctionModel(capture),
        name="history-trim-disabled-test",
        capabilities=[ProcessHistory(history_trimmer())],
    )

    await agent.run("current prompt", message_history=_history(3))

    assert _boundary_texts(seen) == ["turn 0", "turn 1", "turn 2", "current prompt"]


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


async def test_cache_sensitive_prefix_inputs_are_deterministic() -> None:
    agent = _agent(
        instructions="Reply plainly.",
        tool_names=["test_runtime_context", "test_add_numbers"],
    )

    assert _runtime_instructions(agent, include_delegation=False) == (
        f"Reply plainly.\n\n{PLANNING_INSTRUCTIONS}"
    )
    assert _runtime_instructions(agent, include_delegation=False) == _runtime_instructions(
        agent,
        include_delegation=False,
    )
    assert [tool.name for tool in build_runtime_tools(agent)] == [
        tool.name for tool in build_runtime_tools(agent)
    ]


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


def _agent(
    *,
    instructions: str,
    tool_names: list[str] | None = None,
) -> Agent:
    return Agent(
        id=uuid4(),
        name="Runtime Agent",
        slug="runtime-agent",
        instructions=instructions,
        workspace_id=uuid4(),
        created_by=uuid4(),
        tool_names=tool_names or [],
        model_provider="openai",
        model="gpt-5.4-mini",
    )
