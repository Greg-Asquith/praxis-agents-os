"""Model-specific Vertex routing and publisher API behavior."""

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel, ValidationError
from pydantic_ai import Agent, NativeOutput
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models import override_allow_model_requests

from core.settings import Settings, settings
from services.agents.models import (
    build_model,
    close_vertex_clients,
    vertex_mistral_client as mistral,
    vertex_openai_client as vertex,
)
from services.agents.models.domain import ModelConfigurationError
from services.agents.models.list_model_catalog import list_model_catalog
from services.agents.models.registry import get_model
from services.agents.models.resolution import resolve_catalog_model
from services.agents.models.utils import partner_location
from services.agents.models.validate_partner_configuration import validate_partner_configuration

MODELS = (
    ("meta", "llama-4-scout"),
    ("xai", "grok-4-20-non-reasoning"),
    ("mistral", "mistral-small-2503"),
)


@pytest.fixture
async def configured(monkeypatch):
    monkeypatch.setattr(settings, "VERTEX_PARTNER_MODELS_ENABLED", True)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", "test-project")
    monkeypatch.setattr(settings, "VERTEX_PARTNER_MODEL_LOCATIONS", {})
    monkeypatch.setattr(settings, "LLM_HTTP_RETRY_MAX_WAIT_SECONDS", 0)
    monkeypatch.setattr(settings, "LLM_HTTP_RETRY_TOTAL_WAIT_CAP_SECONDS", 0)
    credentials = SimpleNamespace(valid=True)
    credentials.token = "adc-token"
    monkeypatch.setattr(
        vertex.google.auth,
        "default",
        lambda **kwargs: (credentials, None),
    )
    yield
    await close_vertex_clients()


@pytest.mark.parametrize(
    "provider,alias,location,transport",
    [
        ("meta", "llama-4-scout", "us-east5", "chat-completions"),
        ("xai", "grok-4-20-reasoning", "global", "chat-completions"),
        ("mistral", "mistral-small-2503", "europe-west4", "mistral-publisher"),
    ],
)
def test_defaults(configured, provider, alias, location, transport):
    spec = resolve_catalog_model(provider, alias)
    assert (spec.vertex_location, spec.partner_transport, spec.vertex_project) == (
        location,
        transport,
        "test-project",
    )
    assert spec.qualified_id == f"{provider}:{alias}"


def test_override_and_endpoint_client_identity(configured, monkeypatch):
    original = resolve_catalog_model("mistral", "mistral-small-2503")
    first = build_model(original).provider.client._client
    monkeypatch.setattr(
        settings, "VERTEX_PARTNER_MODEL_LOCATIONS", {original.qualified_id: "us-central1"}
    )
    overridden = resolve_catalog_model("mistral", "mistral-small-2503")
    assert overridden.vertex_location == "us-central1"
    assert original.vertex_location == "europe-west4"
    assert build_model(original).provider.client._client is first
    assert build_model(overridden).provider.client._client is not first
    assert (
        build_model(replace(original, vertex_project="another-project")).provider.client._client
        is not first
    )


@pytest.mark.parametrize("value", [[], {"mistral:mistral-small-2503": 1}, {"": "global"}])
def test_invalid_override_shape(value):
    with pytest.raises(ValidationError, match="VERTEX_PARTNER_MODEL_LOCATIONS"):
        Settings(_env_file=None, VERTEX_PARTNER_MODEL_LOCATIONS=value)


@pytest.mark.parametrize("value", ["", "global", "us-central1"])
def test_legacy_setting_rejected(value):
    with pytest.raises(ValidationError, match="was removed"):
        Settings(_env_file=None, VERTEX_PARTNER_LOCATION=value)


@pytest.mark.parametrize(
    "value",
    [
        {"unknown:model": "global"},
        {"google:gemini-3.8-flash": "global"},
        {"meta:llama-4-scout": "global"},
    ],
)
def test_catalog_override_rejection(configured, monkeypatch, value):
    monkeypatch.setattr(settings, "VERTEX_PARTNER_MODEL_LOCATIONS", value)
    for operation in (
        validate_partner_configuration,
        list_model_catalog,
        lambda: resolve_catalog_model(*MODELS[0]),
    ):
        with pytest.raises(ModelConfigurationError):
            operation()


@pytest.mark.parametrize(
    "changes",
    [
        {"partner_transport": None},
        {"vertex_default_location": None},
        {"vertex_supported_locations": ()},
    ],
)
def test_missing_metadata(configured, changes):
    with pytest.raises(ModelConfigurationError):
        partner_location(replace(get_model(*MODELS[0]), **changes))


def install_response(monkeypatch, handler):
    build = vertex._build_retrying_http_client
    for module in (vertex, mistral):
        monkeypatch.setattr(
            module,
            "_build_retrying_http_client",
            lambda **kwargs: build(httpx.MockTransport(handler), **kwargs),
        )


def completion(content="Hello", *, tools=None):
    return {
        "id": "chat-1",
        "object": "chat.completion",
        "created": 1,
        "model": "mistral-small-2503",
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls" if tools else "stop",
                "message": {"role": "assistant", "content": content, "tool_calls": tools},
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
    }


def streaming_response(content="37", *, tool=False):
    delta = (
        {
            "tool_calls": [
                {
                    "index": 0,
                    "id": "probe1234",
                    "function": {"name": "probe_number", "arguments": "{}"},
                }
            ]
        }
        if tool
        else {"content": content}
    )
    chunk = {
        "id": "chat-1",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "mistral-small-2503",
        "choices": [
            {"index": 0, "delta": delta, "finish_reason": "tool_calls" if tool else "stop"}
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
    }
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n",
    )


async def test_concurrent_models_keep_resolved_routing(configured, monkeypatch):
    seen = []

    def respond(request):
        body = json.loads(request.content)
        seen.append((str(request.url), body["model"]))
        assert request.headers["Authorization"] == "Bearer adc-token"
        if "publishers/mistralai" in str(request.url):
            assert "max_tokens" in body and "max_completion_tokens" not in body
        return httpx.Response(200, json=completion())

    install_response(monkeypatch, respond)
    specs = [
        resolve_catalog_model(*model, settings_overrides={"max_tokens": 32}) for model in MODELS
    ]
    models = [build_model(spec) for spec in specs]
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", "changed-after-resolution")
    with override_allow_model_requests(True):
        results = await asyncio.gather(
            *(Agent(model, name="routing_test").run("Hello") for model in models * 2)
        )
    assert all(
        result.usage.input_tokens == 12 and result.usage.output_tokens == 4 for result in results
    )
    assert len(seen) == 6
    for url, model in seen:
        assert "/projects/test-project/" in url
        if model.startswith("meta/"):
            assert "/locations/us-east5/endpoints/openapi/chat/completions" in url
        elif model.startswith("xai/"):
            assert "/locations/global/endpoints/openapi/chat/completions" in url
        else:
            assert model == "mistral-small-2503"
            assert url.endswith(
                "/locations/europe-west4/publishers/mistralai/models/mistral-small-2503@001:rawPredict"
            )
    assert settings.VERTEX_PARTNER_MODEL_LOCATIONS == {}


async def test_publisher_streamed_tool_round_trip(configured, monkeypatch):
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        assert request.url.path.endswith(":streamRawPredict")
        tool_result = any(message["role"] == "tool" for message in body["messages"])
        return streaming_response(tool=not tool_result)

    install_response(monkeypatch, respond)

    def probe_number() -> int:
        return 37

    agent = Agent(
        build_model(resolve_catalog_model(*MODELS[2])), tools=[probe_number], name="publisher_test"
    )
    with override_allow_model_requests(True):
        async with agent.run_stream("Call probe_number") as result:
            assert "".join([text async for text in result.stream_text(delta=True)]) == "37"
            assert (
                result.usage.input_tokens,
                result.usage.output_tokens,
                result.usage.requests,
            ) == (24, 8, 2)
    assert len(requests) == 2
    assert (
        next(message for message in requests[1]["messages"] if message["role"] == "tool")["content"]
        == "37"
    )


async def test_publisher_native_output(configured, monkeypatch):
    class Answer(BaseModel):
        value: int

    def respond(request):
        assert json.loads(request.content)["response_format"]["type"] == "json_schema"
        return httpx.Response(200, json=completion('{"value":37}'))

    install_response(monkeypatch, respond)
    with override_allow_model_requests(True):
        result = await Agent(
            build_model(resolve_catalog_model(*MODELS[2])),
            output_type=NativeOutput(Answer),
            name="json_test",
        ).run("Return 37")
    assert result.output.value == 37


@pytest.mark.parametrize(
    "status,attempts,expected", [(429, 1, 1), (429, 3, 3), (503, 3, 3), (401, 3, 1), (403, 3, 1)]
)
async def test_publisher_http_errors_preserve_status(
    configured, monkeypatch, status, attempts, expected
):
    monkeypatch.setattr(settings, "LLM_HTTP_RETRY_MAX_ATTEMPTS", attempts)
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"message": "private provider detail"}})

    install_response(monkeypatch, respond)
    with override_allow_model_requests(True), pytest.raises(ModelHTTPError) as caught:
        await Agent(build_model(resolve_catalog_model(*MODELS[2])), name="error_test").run("Hello")
    assert caught.value.status_code == status
    assert "private provider detail" in str(caught.value.body)
    assert len(calls) == expected


async def test_stream_cancellation_closes_response_without_retry(configured, monkeypatch):
    started = asyncio.Event()
    closed = asyncio.Event()
    calls = []

    class PendingStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield streaming_response().content.removesuffix(b"data: [DONE]\n\n")
            started.set()
            await asyncio.Event().wait()

        async def aclose(self):
            closed.set()

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=PendingStream()
        )

    install_response(monkeypatch, respond)
    model = build_model(resolve_catalog_model(*MODELS[2]))

    async def consume():
        async with Agent(model, name="cancel_test").run_stream("Hello") as result:
            async for _ in result.stream_text(delta=True):
                pass

    with override_allow_model_requests(True):
        task = asyncio.create_task(consume())
        await asyncio.wait_for(started.wait(), timeout=3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert closed.is_set()
    assert len(calls) == 1
    client = model.provider.client._client
    await close_vertex_clients()
    assert client.is_closed


async def test_publisher_eventual_success(configured, monkeypatch):
    monkeypatch.setattr(settings, "LLM_HTTP_RETRY_MAX_ATTEMPTS", 3)
    calls = []

    def respond(request):
        calls.append(request)
        return (
            httpx.Response(503, json={"error": "busy"})
            if len(calls) < 3
            else httpx.Response(200, json=completion())
        )

    install_response(monkeypatch, respond)
    with override_allow_model_requests(True):
        result = await Agent(build_model(resolve_catalog_model(*MODELS[2])), name="retry_test").run(
            "Hello"
        )
    assert result.output == "Hello"
    assert len(calls) == 3
    assert result.usage.requests == 1


@pytest.mark.parametrize("alias", ["llama-4-scout", "llama-4-maverick"])
@pytest.mark.parametrize("limit", [None, 128])
async def test_meta_requests_include_output_limit(configured, monkeypatch, alias, limit):
    def respond(request):
        body = json.loads(request.content)
        assert body["max_completion_tokens"] == (8192 if limit is None else limit)
        return streaming_response(content="Hello")

    install_response(monkeypatch, respond)
    spec = resolve_catalog_model(
        "meta", alias, settings_overrides={} if limit is None else {"max_tokens": limit}
    )
    with override_allow_model_requests(True):
        async with Agent(build_model(spec), name="meta_limit_test").run_stream("Hello") as result:
            assert await result.get_output() == "Hello"


@pytest.mark.parametrize("alias", ["llama-4-scout", "llama-4-maverick"])
async def test_meta_chart_schema_preserves_local_definition(configured, monkeypatch, alias):
    from copy import deepcopy

    from services.agents.runtime.tools.registry import get_runtime_tool_definition

    definition = get_runtime_tool_definition("build_chart")
    original = deepcopy(definition.serialized_input_schema())
    seen = []

    def inspect_schema(schema):
        if isinstance(schema, list):
            for item in schema:
                inspect_schema(item)
        elif isinstance(schema, dict):
            assert not isinstance(schema.get("additionalProperties"), dict)
            if schema.get("additionalProperties") is True:
                assert "Each additional property value must match:" in schema["description"]
                seen.append(schema)
            for value in schema.values():
                inspect_schema(value)

    def respond(request):
        body = json.loads(request.content)
        tool = body["tools"][0]["function"]
        assert "strict" not in tool
        inspect_schema(tool["parameters"])
        return streaming_response(content="Hello")

    install_response(monkeypatch, respond)
    agent = Agent(
        build_model(resolve_catalog_model("meta", alias)),
        tools=[definition.to_pydantic_tool()],
        name="meta_chart_test",
    )
    with override_allow_model_requests(True):
        async with agent.run_stream("Hello") as result:
            assert await result.get_output() == "Hello"
    assert seen
    assert definition.serialized_input_schema() == original
