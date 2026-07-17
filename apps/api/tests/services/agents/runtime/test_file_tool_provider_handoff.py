"""Offline provider-mapping coverage for rich file tool results."""

from io import BytesIO

import pytest
from pydantic_ai.messages import BinaryContent, ModelRequest, ToolReturnPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider

pytestmark = pytest.mark.asyncio


def _image_tool_return() -> ToolReturnPart:
    return ToolReturnPart(
        tool_name="read_file",
        tool_call_id="read-image",
        content=[
            {"source": "image", "name": "screen.png"},
            BinaryContent(
                data=b"provider-visible-png",
                media_type="image/png",
                identifier="file-1",
            ),
        ],
    )


async def test_openai_maps_image_inside_tool_result() -> None:
    model = OpenAIResponsesModel(
        "gpt-5.4-mini",
        provider=OpenAIProvider(api_key="test"),
    )

    _instructions, inputs = await model._map_messages(
        [ModelRequest(parts=[_image_tool_return()])],
        {},
        ModelRequestParameters(),
    )

    [tool_output] = inputs
    assert tool_output["type"] == "function_call_output"
    assert tool_output["output"][1]["type"] == "input_image"
    assert tool_output["output"][1]["image_url"].startswith("data:image/png;base64,")


async def test_anthropic_maps_image_inside_tool_result() -> None:
    model = AnthropicModel(
        "claude-sonnet-4-6",
        provider=AnthropicProvider(api_key="test"),
    )

    _system, messages = await model._map_message(
        [ModelRequest(parts=[_image_tool_return()])],
        ModelRequestParameters(),
        {},
    )

    [message] = messages
    [tool_result] = message["content"]
    image = tool_result["content"][1]
    assert image["type"] == "image"
    assert image["source"]["media_type"] == "image/png"
    assert isinstance(image["source"]["data"], BytesIO)
    assert image["source"]["data"].read() == b"provider-visible-png"


async def test_google_maps_image_inside_tool_result() -> None:
    model = GoogleModel(
        "gemini-3.1-pro",
        provider=GoogleProvider(api_key="test"),
    )

    _system, messages = await model._map_messages(
        [ModelRequest(parts=[_image_tool_return()])],
        ModelRequestParameters(),
    )

    [message] = messages
    [tool_result] = message["parts"]
    [image] = tool_result["function_response"]["parts"]
    assert image == {
        "inline_data": {
            "data": b"provider-visible-png",
            "mime_type": "image/png",
        }
    }
