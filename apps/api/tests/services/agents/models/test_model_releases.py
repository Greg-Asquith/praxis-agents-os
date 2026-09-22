"""Checks release-specific requests through the installed SDKs without network I/O."""

import json

import httpx2 as httpx
import pytest
from anthropic import AsyncAnthropicVertex
from pydantic import BaseModel, SecretStr
from pydantic_ai import Agent, models
from pydantic_ai.exceptions import UserError
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.anthropic import AnthropicStaleThinkingBlockWarning
from pydantic_ai.tools import ToolDefinition

from core.settings import settings
from services.agents.models import factory
from services.agents.models.domain import ModelConfigurationError
from services.agents.models.resolution import resolve_catalog_model


@pytest.mark.parametrize("model_id", ["gpt-6-sol", "gpt-6-luna"])
@pytest.mark.parametrize(
    "thinking,effort", [(None, None), (False, "none"), ("minimal", "low"), ("high", "high")]
)
async def test_gpt_6_responses_reasoning_and_tools(monkeypatch, model_id, thinking, effort):
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("test-key"))
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "resp_release",
                "object": "response",
                "created_at": 1,
                "model": model_id,
                "status": "completed",
                "output": [],
                "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
            },
        )

    overrides = {"thinking": thinking} if thinking is not None else {}
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(factory, "retrying_http_client", lambda: client)
        model = factory.build_model(
            resolve_catalog_model("openai", model_id, settings_overrides=overrides)
        )
        result = await model.request(
            [ModelRequest(parts=[UserPromptPart("Use the lookup tool.")])],
            None,
            ModelRequestParameters(
                function_tools=[
                    ToolDefinition(
                        name="lookup", parameters_json_schema={"type": "object", "properties": {}}
                    )
                ]
            ),
        )
        assert model.profile["openai_reasoning_enabled_by_default"] is True
        assert model.profile["openai_supports_phase"] is True

    [request] = requests
    body = json.loads(request.content)
    assert request.url.path == "/v1/responses"
    assert body["model"] == model_id
    assert body["reasoning"].get("effort") == effort
    assert body["reasoning"]["context"] == "all_turns"
    assert "reasoning.encrypted_content" in body["include"]
    assert body["tools"][0]["name"] == "lookup"
    assert result.usage.input_tokens == 3


class _Classification(BaseModel):
    label: str


@pytest.fixture(params=[False, True], ids=["direct", "vertex"])
def opus_transport(request, monkeypatch):
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)
    monkeypatch.setattr(settings, "ANTHROPIC_VERTEX_AI", request.param)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", "test-project")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr("test-key"))
    return request.param


@pytest.mark.parametrize("thinking", [None, False, "high"])
async def test_opus_structured_output_uses_native_schema(monkeypatch, opus_transport, thinking):
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "msg_release",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5-5",
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": '{"label":"yes"}'}],
                "usage": {"input_tokens": 3, "output_tokens": 2},
            },
        )

    overrides = {"thinking": thinking} if thinking is not None else {}
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(factory, "retrying_http_client", lambda: client)
        vertex = AsyncAnthropicVertex(
            project_id="test-project",
            region="global",
            access_token="test-token",  # noqa: S106 - offline fixture
            http_client=client,
        )
        monkeypatch.setattr(factory, "get_anthropic_vertex_client", lambda: vertex)
        model = factory.build_model(
            resolve_catalog_model("anthropic", "claude-opus-5-5", settings_overrides=overrides)
        )
        result = await Agent(model, output_type=_Classification).run("Classify this.")
        assert model.profile["anthropic_binds_thinking_blocks"] is True
        with pytest.raises(UserError, match="does not support"):
            await model.request(
                [ModelRequest(parts=[UserPromptPart("Force a tool.")])],
                {"tool_choice": "required"},
                ModelRequestParameters(function_tools=[ToolDefinition(name="lookup")]),
            )

    assert result.output.label == "yes"
    [body] = requests
    assert body["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body.get("tool_choice", {}).get("type") not in {"any", "tool"}
    if thinking == "high":
        assert body["output_config"]["effort"] == "high"


@pytest.mark.parametrize("mode", ["disabled", "enabled"])
def test_opus_rejects_incompatible_explicit_thinking(monkeypatch, mode):
    monkeypatch.setattr(settings, "ANTHROPIC_VERTEX_AI", False)
    with pytest.raises(ModelConfigurationError, match="requires adaptive thinking"):
        factory.build_model(
            resolve_catalog_model(
                "anthropic",
                "claude-opus-5-5",
                settings_overrides={"anthropic_thinking": {"type": mode}},
            )
        )


async def test_opus_tool_loop_preserves_thinking_and_recovers_binding(monkeypatch, opus_transport):
    requests = []
    tool_calls = []
    thinking = {"type": "thinking", "thinking": "Checking the record.", "signature": "signed-block"}

    def lookup() -> str:
        tool_calls.append("lookup")
        return "Record found"

    def respond(request):
        requests.append(json.loads(request.content))
        if len(requests) == 2:
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
        content = (
            [thinking, {"type": "tool_use", "id": "lookup-1", "name": "lookup", "input": {}}]
            if len(requests) == 1
            else [{"type": "text", "text": "Record found"}]
        )
        return httpx.Response(
            200,
            json={
                "id": f"msg_{len(requests)}",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5-5",
                "content": content,
                "stop_reason": "tool_use" if len(requests) == 1 else "end_turn",
                "usage": {"input_tokens": 3, "output_tokens": 2},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(factory, "retrying_http_client", lambda: client)
        vertex = AsyncAnthropicVertex(
            project_id="test-project",
            region="global",
            access_token="test-token",  # noqa: S106 - offline fixture
            http_client=client,
        )
        monkeypatch.setattr(factory, "get_anthropic_vertex_client", lambda: vertex)
        model = factory.build_model(resolve_catalog_model("anthropic", "claude-opus-5-5"))
        with pytest.warns(
            AnthropicStaleThinkingBlockWarning, match="rejected a replayed thinking block"
        ):
            result = await Agent(model, tools=[lookup]).run("Look up the record.")

    assert result.output == "Record found"
    assert tool_calls == ["lookup"]
    assert len(requests) == 3
    assert requests[0]["tool_choice"]["type"] == "auto"
    assert requests[1]["messages"][1]["content"][0] == thinking
    assert requests[2]["messages"] == requests[1]["messages"]
    assert requests[2]["thinking"]["block_binding"]["prefix_mismatch_behavior"] == "drop_block"
