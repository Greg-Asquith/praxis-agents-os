"""Qualifies native helper fields and responses through installed provider adapters."""

import json

import httpx2 as httpx
import pytest
from pydantic import SecretStr
from pydantic_ai import Agent, models
from pydantic_ai.capabilities import NativeTool
from pydantic_ai.messages import NativeToolReturnPart
from pydantic_ai.native_tools import CodeExecutionTool, WebFetchTool, WebSearchTool

from core.settings import settings
from services.agents.models import factory
from services.agents.models.domain import ResolvedModel
from services.agents.runtime.tools.native.classifier import _classification_output_model
from services.agents.runtime.tools.native.web_search import _web_search_sources
from tests.support.google_native import mock_google_native


@pytest.mark.parametrize("vertex", [False, True], ids=["direct", "vertex"])
@pytest.mark.parametrize("action", ["search", "fetch", "code", "classification"])
async def test_google_native_helper_wire_and_response(monkeypatch, vertex, action):
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", vertex)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", "helper-probe")
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_LOCATION", "global")
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None if vertex else SecretStr("test-key"))
    model_id = {
        "classification": "gemini-3.5-flash-lite",
        "code": "gemini-3.8-flash",
        "search": "gemini-3.8-flash",
    }.get(action, "gemini-3.7-flash")
    parts = [{"text": "Result"}]
    candidate = {"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}
    capabilities = []
    output_type = str
    if action == "search":
        capabilities = [NativeTool(WebSearchTool())]
        candidate["groundingMetadata"] = {
            "webSearchQueries": ["example"],
            "groundingChunks": [{"web": {"uri": "https://example.com", "title": "Example"}}],
        }
    elif action == "fetch":
        capabilities = [NativeTool(WebFetchTool())]
        candidate["urlContextMetadata"] = {
            "urlMetadata": [
                {
                    "retrievedUrl": "https://example.com",
                    "urlRetrievalStatus": "URL_RETRIEVAL_STATUS_SUCCESS",
                }
            ]
        }
    elif action == "code":
        capabilities = [NativeTool(CodeExecutionTool())]
        parts[:0] = [
            {"executableCode": {"language": "PYTHON", "code": "print(2 + 2)"}},
            {"codeExecutionResult": {"outcome": "OUTCOME_OK", "output": "4\n"}},
        ]
    else:
        output_type = _classification_output_model(["yes", "no"])
        parts[:] = [
            {
                "functionCall": {
                    "name": "final_result",
                    "args": {"results": [{"index": 0, "label": "yes"}]},
                }
            }
        ]

    def respond(request):
        return httpx.Response(
            200,
            json={
                "candidates": [candidate],
                "usageMetadata": {
                    "promptTokenCount": 10,
                    "candidatesTokenCount": 5,
                    "totalTokenCount": 15,
                },
            },
        )

    async with mock_google_native(monkeypatch, respond, vertex=vertex) as requests:
        model = factory.build_model(
            ResolvedModel(
                provider="google",
                model=model_id,
                transport_model=model_id,
                settings={},
                max_steps=3,
            )
        )
        result = await Agent(model, capabilities=capabilities, output_type=output_type).run(
            "Inspect https://example.com"
        )
        await model.provider.client.aio.aclose()
        model.provider.client.close()

    assert len(requests) == 1
    request = requests[0]
    assert request.url.path.endswith(f"/models/{model_id}:generateContent")
    if vertex:
        assert request.url.host == "aiplatform.googleapis.com"
        assert "/projects/helper-probe/locations/global/publishers/google/" in request.url.path
        assert request.headers["authorization"] == "Bearer test-adc"
        assert "x-goog-api-key" not in request.headers
    else:
        assert request.url.host == "generativelanguage.googleapis.com"
        assert request.headers["x-goog-api-key"] == "test-key"
    body = json.loads(request.content)
    if action == "classification":
        declaration = body["tools"][0]["functionDeclarations"][0]
        assert declaration["name"] == "final_result"
        assert result.output.results[0].label == "yes"
    else:
        key = {"search": "googleSearch", "fetch": "urlContext", "code": "codeExecution"}[action]
        assert body["tools"] == [{key: {}}]
        assert result.output == "Result"
        returns = [
            part
            for message in result.all_messages()
            for part in message.parts
            if isinstance(part, NativeToolReturnPart)
        ]
        assert len(returns) == 1
        if action == "search":
            assert _web_search_sources(result.all_messages())[0].url == "https://example.com"
        elif action == "code":
            assert returns[0].content["output"] == "4\n"
        else:
            assert returns[0].tool_name == "web_fetch"
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 5


@pytest.mark.parametrize(
    ("provider", "vertex", "action"),
    [
        ("anthropic", False, "search"),
        ("anthropic", True, "search"),
        ("anthropic", False, "fetch"),
        ("anthropic", False, "code"),
        ("anthropic", False, "classification"),
        ("anthropic", True, "classification"),
        ("openai", False, "search"),
        ("openai", False, "code"),
        ("openai", False, "classification"),
    ],
)
async def test_anthropic_and_openai_helper_requests(monkeypatch, provider, vertex, action):
    from anthropic import AsyncAnthropicVertex

    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)
    monkeypatch.setattr(settings, "ANTHROPIC_VERTEX_AI", vertex)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None if vertex else SecretStr("test-key"))
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("test-key"))
    monkeypatch.setattr(settings, "OPENAI_BASE_URL", None)
    requests = []
    model_id = (
        "gpt-5.6-luna"
        if provider == "openai"
        else "claude-haiku-4-5"
        if action == "classification"
        else "claude-sonnet-5"
    )
    output_type = _classification_output_model(["yes", "no"]) if action == "classification" else str
    capabilities = (
        []
        if action == "classification"
        else [
            NativeTool(
                {
                    "search": WebSearchTool,
                    "fetch": WebFetchTool,
                    "code": CodeExecutionTool,
                }[action]()
            )
        ]
    )
    args = {"results": [{"index": 0, "label": "yes"}]}
    if provider == "anthropic":
        content = (
            [{"type": "tool_use", "id": "tool_result", "name": "final_result", "input": args}]
            if action == "classification"
            else [{"type": "text", "text": "Result"}]
        )
        response = {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": model_id,
            "content": content,
            "stop_reason": "tool_use" if action == "classification" else "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
    else:
        output = (
            [
                {
                    "type": "function_call",
                    "id": "fc_test",
                    "call_id": "call_test",
                    "name": "final_result",
                    "arguments": json.dumps(args),
                    "status": "completed",
                }
            ]
            if action == "classification"
            else [
                {
                    "type": "message",
                    "id": "msg_test",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "Result", "annotations": []}],
                }
            ]
        )
        response = {
            "id": "resp_test",
            "object": "response",
            "created_at": 1,
            "status": "completed",
            "model": model_id,
            "output": output,
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=response)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(factory, "retrying_http_client", lambda: client)
        if vertex:
            sdk = AsyncAnthropicVertex(
                project_id="helper-probe",
                region="global",
                access_token="test-token",  # noqa: S106 - offline SDK fixture
                http_client=client,
                max_retries=0,
            )
            monkeypatch.setattr(factory, "get_anthropic_vertex_client", lambda: sdk)
        model = factory.build_model(
            ResolvedModel(
                provider=provider,
                model=model_id,
                transport_model=model_id,
                settings={},
                max_steps=3,
            )
        )
        result = await Agent(model, capabilities=capabilities, output_type=output_type).run(
            "Inspect this item"
        )
    assert len(requests) == 1
    request = requests[0]
    body = json.loads(request.content)
    if vertex:
        assert request.url.host == "aiplatform.googleapis.com"
        assert (
            request.url.path
            == f"/v1/projects/helper-probe/locations/global/publishers/anthropic/models/{model_id}:rawPredict"
        )
        assert request.headers["authorization"] == "Bearer test-token"
        assert "x-api-key" not in request.headers
    else:
        assert request.url.path == ("/v1/messages" if provider == "anthropic" else "/v1/responses")
        assert body["model"] == model_id
    if action == "classification":
        assert body["tools"][0]["name"] == "final_result"
        assert result.output.results[0].label == "yes"
    else:
        tool_type = body["tools"][0]["type"]
        expected = {
            "search": "web_search",
            "fetch": "web_fetch",
            "code": "code_execution" if provider == "anthropic" else "code_interpreter",
        }[action]
        assert tool_type.startswith(expected)
        if vertex:
            assert tool_type == "web_search_20250305"
        if provider == "openai" and action == "code":
            assert body["tools"][0]["container"] == {"type": "auto"}
        assert result.output == "Result"
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 5


@pytest.mark.parametrize("action", ["search", "fetch", "code", "classification"])
@pytest.mark.parametrize("provider", ["meta", "mistral", "xai"])
def test_vertex_partners_remain_outside_helper_availability(monkeypatch, action, provider):
    from services.agents.runtime.tools.native import classifier, run_code, web_fetch, web_search

    module, available = {
        "search": (web_search, web_search.configured_native_search_providers),
        "fetch": (web_fetch, web_fetch.configured_native_fetch_providers),
        "code": (run_code, run_code.configured_native_run_code_providers),
        "classification": (classifier, classifier.configured_classifier_providers),
    }[action]
    monkeypatch.setattr(module, "is_provider_configured", lambda _provider: True)
    assert provider not in available()


@pytest.mark.parametrize("action", ["fetch", "code"])
def test_anthropic_vertex_helper_override_fails_before_dispatch(monkeypatch, action):
    from pydantic_ai import ModelRetry

    from services.agents.runtime.tools.native import run_code, web_fetch

    monkeypatch.setattr(settings, "ANTHROPIC_VERTEX_AI", True)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", "helper-probe")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr("unused-direct-key"))
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", False)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)
    resolve = (
        web_fetch.resolve_web_fetch_model if action == "fetch" else run_code.resolve_run_code_model
    )
    with pytest.raises(ModelRetry, match="providers are configured"):
        resolve(None, model_provider="anthropic")
