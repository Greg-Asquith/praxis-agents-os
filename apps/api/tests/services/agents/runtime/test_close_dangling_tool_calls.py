# apps/api/tests/services/agents/runtime/test_close_dangling_tool_calls.py

"""Tests for closing dangling tool calls in loaded runtime history."""

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from services.agents.runtime.persistence import (
    SYNTHESIZED_TOOL_RETURN_CONTENT,
    close_dangling_tool_calls,
)


def test_closes_trailing_dangling_call() -> None:
    messages = [
        ModelRequest(parts=[UserPromptPart("do it")]),
        ModelResponse(
            parts=[
                ToolCallPart(tool_name="run_workflow", args={"code": "x"}, tool_call_id="call-1")
            ]
        ),
    ]

    repaired = close_dangling_tool_calls(messages)

    assert len(repaired) == 3
    closing = repaired[-1]
    assert isinstance(closing, ModelRequest)
    [part] = closing.parts
    assert isinstance(part, ToolReturnPart)
    assert part.tool_call_id == "call-1"
    assert part.content == SYNTHESIZED_TOOL_RETURN_CONTENT
    # Idempotent: a repaired history has nothing left to close.
    assert close_dangling_tool_calls(repaired) is repaired


def test_closes_mid_history_dangling_call_into_following_request() -> None:
    messages = [
        ModelResponse(
            parts=[
                ToolCallPart(tool_name="a", args={}, tool_call_id="call-1"),
                ToolCallPart(tool_name="b", args={}, tool_call_id="call-2"),
            ]
        ),
        ModelRequest(
            parts=[
                ToolReturnPart(tool_name="a", content="ok", tool_call_id="call-1"),
                UserPromptPart("next"),
            ]
        ),
        ModelResponse(parts=[TextPart("done")]),
    ]

    repaired = close_dangling_tool_calls(messages)

    assert len(repaired) == 3
    request = repaired[1]
    assert isinstance(request, ModelRequest)
    assert [type(part).__name__ for part in request.parts] == [
        "ToolReturnPart",
        "ToolReturnPart",
        "UserPromptPart",
    ]
    synthesized = request.parts[1]
    assert isinstance(synthesized, ToolReturnPart)
    assert synthesized.tool_call_id == "call-2"
