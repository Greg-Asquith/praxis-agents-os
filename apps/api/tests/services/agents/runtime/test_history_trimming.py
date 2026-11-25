# apps/api/tests/services/agents/runtime/test_history_trimming.py

"""Tests for cache-stable runtime history trimming and compaction."""

from uuid import uuid4

import pytest
from pydantic_ai import Agent as PydanticAgent, ModelRetry
from pydantic_ai.capabilities import ProcessHistory
from pydantic_ai.exceptions import ModelContextWindowExceededError
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
from services.agents.runtime.capabilities import build_runtime_capabilities
from services.agents.runtime.history import (
    AUTOMATIC_SUMMARY_PREFIX,
    HistoryCompaction,
    TokenBudget,
    history_trimmer,
    trim_history,
)
from services.agents.runtime.progress_review.verdict import STEER_METADATA_KEY

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


async def test_trim_history_does_not_cut_at_progress_review_steer() -> None:
    history = _history(41)
    steer = ModelRequest(
        parts=[UserPromptPart("Progress check: wrap up.")],
        metadata={STEER_METADATA_KEY: True},
    )
    history[39:39] = [steer, ModelResponse(parts=[TextPart("steered reply")])]

    trimmed = trim_history(history, max_turns=40, keep_turns=20)

    assert trimmed[0] is history[42]
    assert _boundary_texts(trimmed)[0] == "turn 20"


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


async def test_trim_history_preserves_dropped_capability_and_skill_loads_without_duplicates() -> (
    None
):
    history = _history_with_capability_loads(
        dropped_ids=["internal-a", "skill:a", "skill:b"],
        kept_ids=["skill:b"],
    )

    trimmed = trim_history(history, max_turns=40, keep_turns=20)

    synthetic_response = trimmed[1]
    synthetic_request = trimmed[2]
    assert isinstance(synthetic_response, ModelResponse)
    assert isinstance(synthetic_request, ModelRequest)
    assert [part.tool_call_id for part in synthetic_response.parts] == [
        "load-internal-a",
        "load-skill-a",
    ]
    assert [part.tool_call_id for part in synthetic_request.parts] == [
        "load-internal-a",
        "load-skill-a",
    ]


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


async def test_token_budget_trims_few_large_turns_at_a_stable_boundary() -> None:
    # Each turn is 100 estimated tokens; the budget holds 800 and trims in steps of 200.
    budget = TokenBudget(limit=800, chars_per_token=4.0)

    first_kept = [
        _boundary_texts(_trim_to_budget(_large_turns(count), budget))[0] for count in range(8, 13)
    ]

    assert first_kept == ["turn 0", "turn 2", "turn 2", "turn 4", "turn 4"]


async def test_token_budget_counts_what_the_model_sees_not_card_metadata() -> None:
    history = _large_turns(4)
    for message in history:
        for part in message.parts:
            if isinstance(part, ToolReturnPart):
                part.metadata = {"card": "x" * 100_000}

    assert _trim_to_budget(history, TokenBudget(limit=400, chars_per_token=4.0)) is history


async def test_token_budget_drops_every_prior_turn_only_at_a_fresh_prompt() -> None:
    budget = TokenBudget(limit=50, chars_per_token=4.0)
    fresh = [*_large_turns(2), _user_request("current", run_id="run-now")]
    resumed = [
        *_large_turns(2),
        ModelRequest(
            parts=[ToolReturnPart(tool_name="lookup", content="ok", tool_call_id="pending")],
            run_id="run-now",
        ),
    ]

    assert _boundary_texts(_trim_to_budget(fresh, budget)) == ["current"]
    assert _boundary_texts(_trim_to_budget(resumed, budget))[0] == "turn 1"


async def test_trimmer_repeats_a_fresh_load_cut_and_keeps_its_watermark_within_a_run() -> None:
    budget = TokenBudget(limit=400, chars_per_token=4.0)
    keys = tuple(uuid4() for _ in range(6))
    trimmer = history_trimmer(budget=budget, boundary_keys=keys)

    current_run = [
        _user_request("current", run_id="run-now"),
        *_large_tool_exchange("a", run_id="run-now"),
        *_large_tool_exchange("b", run_id="run-now"),
    ]

    first = trimmer([*_large_turns(6), current_run[0]])
    second = trimmer([*first, *current_run[1:]])
    fresh = _trim_to_budget([*_large_turns(6), *current_run], budget)

    assert _boundary_texts(first)[0] == "turn 3"
    assert _boundary_texts(second)[0] == "turn 4"
    assert _boundary_texts(second) == _boundary_texts(fresh)
    assert trimmer(second) is second
    assert trimmer.watermark_key == keys[4]


async def test_context_overflow_retries_with_a_shorter_history_that_later_requests_keep() -> None:
    sent_boundaries: list[list[str]] = []

    async def model(messages: list[ModelMessage], _info: object):
        sent_boundaries.append(_boundary_texts(messages))
        if len(sent_boundaries) == 1:
            raise ModelContextWindowExceededError("test-model", "prompt is too long")
        yield "draft" if len(sent_boundaries) == 2 else "ok"

    async def ignore_events(_ctx: object, events: object) -> None:
        async for _event in events:
            pass

    agent = PydanticAgent(
        FunctionModel(stream_function=model),
        name="history-overflow-test",
        capabilities=build_runtime_capabilities(
            None,
            # The estimate fits, as when the real tokenizer is denser than the estimate.
            history_compaction=HistoryCompaction(
                budget=TokenBudget(limit=700, chars_per_token=4.0)
            ),
        ),
    )

    @agent.output_validator
    def ask_again_once(output: str) -> str:
        if output == "draft":
            raise ModelRetry("Try again.")
        return output

    result = await agent.run(
        "current prompt",
        message_history=_large_turns(6),
        event_stream_handler=ignore_events,
    )

    assert result.output == "ok"
    assert [boundaries[0] for boundaries in sent_boundaries] == ["turn 0", "turn 3", "turn 3"]
    assert _boundary_texts(result.new_messages()) == ["current prompt"]


async def test_context_overflow_fails_when_nothing_more_can_be_trimmed() -> None:
    def model(_messages: list[ModelMessage], _info: object) -> ModelResponse:
        raise ModelContextWindowExceededError("test-model", "prompt is too long")

    agent = PydanticAgent(
        FunctionModel(model),
        name="history-overflow-test",
        capabilities=build_runtime_capabilities(
            None,
            history_compaction=HistoryCompaction(
                budget=TokenBudget(limit=700, chars_per_token=4.0)
            ),
        ),
    )

    with pytest.raises(ModelContextWindowExceededError):
        await agent.run("current prompt")


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
        message_history=_history_with_capability_loads(dropped_ids=["internal-a"]),
    )

    assert _load_capability_call_ids(result.all_messages()) == ["load-internal-a"]
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
    """Load `skill:<name>` with load_skill and anything else with load_capability."""
    suffix = capability_id.replace(":", "-")
    tool_call_id = f"load-{suffix}"
    content = {"instructions": f"Instructions for {capability_id}"}
    if capability_id.startswith("skill:"):
        call: ToolCallPart = ToolCallPart(
            tool_name="load_skill",
            args={"name": capability_id.removeprefix("skill:")},
            tool_call_id=tool_call_id,
        )
        result: ToolReturnPart = ToolReturnPart(
            tool_name="load_skill", content=content, tool_call_id=tool_call_id
        )
    else:
        call = LoadCapabilityCallPart(args={"id": capability_id}, tool_call_id=tool_call_id)
        result = LoadCapabilityReturnPart(content=content, tool_call_id=tool_call_id)
    return [
        _user_request(f"turn {index}"),
        ModelResponse(parts=[call]),
        ModelRequest(parts=[result]),
        ModelResponse(parts=[TextPart(f"reply {index}")]),
    ]


def _user_request(content: str, *, run_id: str | None = None) -> ModelRequest:
    return ModelRequest(parts=[UserPromptPart(content)], run_id=run_id)


def _trim_to_budget(history: list[ModelMessage], budget: TokenBudget) -> list[ModelMessage]:
    return trim_history(history, max_turns=40, keep_turns=20, budget=budget)


def _large_turns(turn_count: int) -> list[ModelMessage]:
    messages: list[ModelMessage] = []
    for index in range(turn_count):
        messages.append(_user_request(f"turn {index}"))
        messages.extend(_large_tool_exchange(str(index)))
        messages.append(ModelResponse(parts=[TextPart("done")]))
    return messages


def _large_tool_exchange(label: str, *, run_id: str | None = None) -> list[ModelMessage]:
    """One tool round of 97 estimated tokens at four characters per token."""
    return [
        ModelResponse(
            parts=[ToolCallPart(tool_name="report", args="{}", tool_call_id=f"report-{label}")],
            run_id=run_id,
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="report", content="x" * 192, tool_call_id=f"report-{label}"
                )
            ],
            run_id=run_id,
        ),
    ]


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
