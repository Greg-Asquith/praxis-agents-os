# apps/api/tests/services/conversations/test_conversation_naming.py

"""Service tests for structured conversation title generation."""

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from services.conversations.naming import (
    fallback_conversation_title,
    generate_conversation_title,
)


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
