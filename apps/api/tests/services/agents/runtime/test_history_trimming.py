# apps/api/tests/services/agents/runtime/test_history_trimming.py

"""Tests for cache-stable runtime history trimming and compaction."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic_ai import Agent as PydanticAgent, RunContext
from pydantic_ai.capabilities import ProcessHistory
from pydantic_ai.messages import (
    LoadCapabilityCallPart,
    LoadCapabilityReturnPart,
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage, RunUsage

from core.settings import settings
from models.agent import Agent
from services.agents.runtime import history as history_module
from services.agents.runtime.history import (
    AUTOMATIC_SUMMARY_PREFIX,
    PERSISTED_MESSAGE_ID_METADATA_KEY,
    history_exceeds_context_budget,
    history_trimmer,
    trim_history,
    trim_watermark_key,
)
from services.agents.runtime.loop import _runtime_instructions
from services.agents.runtime.prompt import (
    APPROVAL_INSTRUCTIONS,
    FILE_LINK_INSTRUCTIONS,
    KNOWLEDGE_INSTRUCTIONS,
    MEMORY_INSTRUCTIONS,
    PLANNING_INSTRUCTIONS,
    UNTRUSTED_CONTENT_INSTRUCTIONS,
)
from services.agents.runtime.tools import build_runtime_tools
from utils.tokens import estimate_tokens

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


async def test_summary_prefix_is_byte_stable_at_a_fixed_watermark() -> None:
    shared_history = _history(41)
    first = trim_history(
        shared_history,
        max_turns=40,
        keep_turns=20,
        summary="Stable summary.",
    )
    second = trim_history(
        [*shared_history, *_history(18)],
        max_turns=40,
        keep_turns=20,
        summary="Stable summary.",
    )

    first_prefix = ModelMessagesTypeAdapter.dump_json(first[:2])
    second_prefix = ModelMessagesTypeAdapter.dump_json(second[:2])
    assert first_prefix == second_prefix


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


async def test_watermark_uses_the_persisted_boundary_message_id() -> None:
    watermark_id = uuid4()
    history = _history(41)
    history[40] = replace(
        history[40],
        metadata={PERSISTED_MESSAGE_ID_METADATA_KEY: str(watermark_id)},
    )

    assert trim_watermark_key(history, max_turns=40, keep_turns=20) == watermark_id


async def test_context_pressure_uses_model_calibrated_token_budget() -> None:
    history = _history(3)

    assert history_exceeds_context_budget(
        history,
        system_prompt="system",
        context_window=100,
        chars_per_token=4.0,
        context_fraction=0.6,
    )
    assert not history_exceeds_context_budget(
        [],
        system_prompt="short",
        context_window=100,
        chars_per_token=4.0,
        context_fraction=0.6,
    )


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


async def test_cache_sensitive_static_prefix_inputs_are_deterministic() -> None:
    agent = _agent(
        instructions="Reply plainly.",
        tool_names=["test_runtime_context", "test_add_numbers"],
    )

    assert _runtime_instructions(agent, include_delegation=False).startswith(
        f"Reply plainly.\n\n{PLANNING_INSTRUCTIONS.rstrip()}\n\n"
        f"{APPROVAL_INSTRUCTIONS.rstrip()}\n\n"
        f"{FILE_LINK_INSTRUCTIONS.rstrip()}\n\n"
        f"{KNOWLEDGE_INSTRUCTIONS.rstrip()}\n\n{MEMORY_INSTRUCTIONS.rstrip()}\n\n"
        f"{UNTRUSTED_CONTENT_INSTRUCTIONS}"
    )
    assert [tool.name for tool in build_runtime_tools(agent)] == [
        tool.name for tool in build_runtime_tools(agent)
    ]


@pytest.mark.parametrize(
    ("case", "tokens", "window", "addition", "expected_pressure", "expected_ratio"),
    [
        ("first-request", 0, 100_000, 0, False, None),
        ("unknown-usage", 0, 100_000, 0, False, None),
        ("unknown-window", 60_001, None, 0, False, None),
        ("below-threshold", 59_999, 100_000, 0, False, 0.59999),
        ("at-threshold", 60_000, 100_000, 0, False, 0.6),
        ("above-threshold", 60_001, 100_000, 0, True, 0.60001),
        ("large-prompt", 10, 100_000, 250_000, True, 0.0001),
        ("large-tool-return", 10, 100_000, 250_000, True, 0.0001),
        ("different-model", 60_001, 100_000, 0, True, 0.60001),
        ("changed-window", 60_001, 50_000, 0, True, 1.20002),
        ("azure-override", 60_001, 1_000_000, 0, False, 0.060001),
    ],
)
async def test_observed_pressure_comparison(
    case: str,
    tokens: int,
    window: int | None,
    addition: int,
    expected_pressure: bool,
    expected_ratio: float | None,
    monkeypatch: pytest.MonkeyPatch,
    record_property,
) -> None:
    history = _history(3)
    if case == "first-request":
        history = []
    elif case == "large-tool-return":
        history.extend(
            [
                ModelResponse(parts=[ToolCallPart("lookup", {}, "lookup-1")]),
                ModelRequest(parts=[ToolReturnPart("lookup", "x" * addition, "lookup-1")]),
            ]
        )
    response = next((m for m in reversed(history) if isinstance(m, ModelResponse)), None)
    if response is not None:
        response.usage = RequestUsage(input_tokens=tokens)
        response.model_name = "previous-model" if case == "different-model" else "comparison"
    history.append(
        ModelRequest(
            parts=[
                UserPromptPart(
                    "x" * addition if case == "large-prompt" else "Continue",
                )
            ],
            run_id="current",
        )
    )
    timestamp = datetime(2026, 9, 9, tzinfo=UTC)
    history = [
        replace(
            m,
            timestamp=timestamp,
            parts=[
                replace(p, timestamp=timestamp) if hasattr(p, "timestamp") else p for p in m.parts
            ],
        )
        for m in history
    ]
    model = FunctionModel(
        lambda _messages, _info: ModelResponse(parts=[TextPart("ok")]),
        model_name="comparison",
        profile={"context_window": window},
    )
    ctx = RunContext(deps=None, model=model, usage=RunUsage(), messages=history)
    observed = ctx.context_window_used
    assert observed == expected_ratio
    configured_window = 100_000 if case == "azure-override" else (window or 100_000)
    estimates = []

    def capture_estimate(text: str, *, chars_per_token: float) -> int:
        estimate = estimate_tokens(text, chars_per_token=chars_per_token)
        estimates.append(estimate)
        return estimate

    monkeypatch.setattr(history_module, "estimate_tokens", capture_estimate)
    estimated = history_exceeds_context_budget(
        history,
        system_prompt="system",
        context_window=configured_window,
        chars_per_token=4.0,
        context_fraction=0.6,
    )
    combined = estimated or (observed is not None and observed > 0.6)
    assert estimated == (addition > 0)
    assert combined == expected_pressure
    keys = tuple(uuid4() for _ in range(3)) if response is not None else ()
    boundaries = []
    for pressure in (estimated, combined):
        trimmed = trim_history(history, max_turns=4, keep_turns=2, token_pressure=pressure)
        watermark = trim_watermark_key(
            history,
            max_turns=4,
            keep_turns=2,
            token_pressure=pressure,
            boundary_keys=keys,
        )
        assert watermark == (keys[2] if pressure else None)
        boundary = _boundary_texts(trimmed)[0]
        assert boundary == ("turn 2" if pressure else ("turn 0" if keys else "Continue"))
        boundaries.append(boundary)
        if case == "large-tool-return":
            assert _tool_call_ids(trimmed) == _tool_return_ids(trimmed) == {"lookup-1"}
    record_property(
        "comparison",
        {
            "configured_window": configured_window,
            "profile_window": window,
            "estimated_input": estimates[0],
            "observed_ratio": observed,
            "addition_characters": addition,
            "current_boundary": boundaries[0],
            "combined_boundary": boundaries[1],
        },
    )


async def test_observed_pressure_remains_high_after_summary_and_skill_preserving_trim() -> None:
    history = _history_with_capability_loads(dropped_ids=["skill-a"])
    history[-1].usage = RequestUsage(input_tokens=80_000)
    history[-1].model_name = "comparison"
    history.append(ModelRequest(parts=[UserPromptPart("Continue")], run_id="current"))
    model = FunctionModel(
        lambda _messages, _info: ModelResponse(parts=[TextPart("ok")]),
        model_name="comparison",
        profile={"context_window": 100_000},
    )
    trimmed = trim_history(history, max_turns=40, keep_turns=20, summary="Earlier decisions.")
    reloaded = ModelMessagesTypeAdapter.validate_json(ModelMessagesTypeAdapter.dump_json(trimmed))
    ctx = RunContext(deps=None, model=model, usage=RunUsage(), messages=reloaded)
    assert ctx.context_window_used == 0.8
    assert not history_exceeds_context_budget(
        reloaded,
        system_prompt="system",
        context_window=100_000,
        chars_per_token=4.0,
        context_fraction=0.6,
    )
    retained = trim_history(reloaded, max_turns=40, keep_turns=20)
    combined = trim_history(
        reloaded,
        max_turns=40,
        keep_turns=20,
        token_pressure=True,
        summary="Earlier decisions.",
    )
    assert _boundary_texts(retained)[0] == "turn 20"
    assert _boundary_texts(combined)[0] == "turn 39"
    for messages in (retained, combined):
        assert _load_capability_call_ids(messages) == ["load-skill-a"]
        assert _tool_return_ids(messages) == {"load-skill-a"}
        assert sum(AUTOMATIC_SUMMARY_PREFIX in text for text in _boundary_texts(messages)) == 1


async def test_context_hook_observes_each_response_but_not_the_next_tool_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AGENT_HISTORY_MAX_TURNS", 4)
    monkeypatch.setattr(settings, "AGENT_HISTORY_KEEP_TURNS", 2)
    trimmer = history_trimmer()
    observations = []
    requests = []

    def observe(ctx: RunContext[None], messages: list[ModelMessage]) -> list[ModelMessage]:
        estimated = history_exceeds_context_budget(
            messages,
            system_prompt="system",
            context_window=100_000,
            chars_per_token=4.0,
            context_fraction=0.6,
        )
        observations.append((ctx.context_window_used, estimated))
        return trimmer(messages)

    def respond(messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        requests.append(messages)
        if len(requests) < 3:
            return ModelResponse(
                parts=[
                    ToolCallPart("lookup", {"large": len(requests) == 2}, f"lookup-{len(requests)}")
                ],
                usage=RequestUsage(input_tokens=80_000 if len(requests) == 1 else 10),
            )
        return ModelResponse(parts=[TextPart("done")])

    agent = PydanticAgent(
        FunctionModel(respond, profile={"context_window": 100_000}),
        name="observed-context-comparison",
        capabilities=[ProcessHistory(observe)],
    )

    @agent.tool_plain
    def lookup(large: bool) -> str:
        return "x" * (250_000 if large else 1)

    result = await agent.run("Continue", message_history=_history(3))
    assert result.output == "done"
    assert observations == [(None, False), (0.8, False), (0.0001, True)]
    assert trimmer.watermark_key is None
    assert [_boundary_texts(messages)[0] for messages in requests] == ["turn 0"] * 3
    assert (
        _tool_call_ids(requests[-1])
        == _tool_return_ids(requests[-1])
        == {
            "lookup-1",
            "lookup-2",
        }
    )


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
