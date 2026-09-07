# apps/api/tests/services/agents/models/test_retry_transport.py

"""Provider HTTP retry transport behavior."""

import httpx
import pytest
from pydantic_ai.models import DEFAULT_HTTP_TIMEOUT

from core.settings import settings
from services.agents.models.utils import _build_retrying_http_client

pytestmark = pytest.mark.asyncio


def _fast_retry_settings(monkeypatch, *, attempts: int) -> None:
    monkeypatch.setattr(settings, "LLM_HTTP_RETRY_MAX_ATTEMPTS", attempts)
    monkeypatch.setattr(settings, "LLM_HTTP_RETRY_MAX_WAIT_SECONDS", 0.001)
    monkeypatch.setattr(settings, "LLM_HTTP_RETRY_TOTAL_WAIT_CAP_SECONDS", 0.001)


async def test_retrying_http_client_uses_provider_request_timeout() -> None:
    client = _build_retrying_http_client(wrapped=httpx.MockTransport(lambda _request: None))
    try:
        assert client.timeout.connect == 5
        assert client.timeout.read == DEFAULT_HTTP_TIMEOUT
        assert client.timeout.write == DEFAULT_HTTP_TIMEOUT
        assert client.timeout.pool == DEFAULT_HTTP_TIMEOUT
    finally:
        await client.aclose()


async def test_retrying_http_client_retries_429_then_succeeds(monkeypatch) -> None:
    _fast_retry_settings(monkeypatch, attempts=2)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, request=request)
        return httpx.Response(200, json={"ok": True}, request=request)

    client = _build_retrying_http_client(wrapped=httpx.MockTransport(handler))
    try:
        response = await client.get("https://provider.example/test")
    finally:
        await client.aclose()

    assert response.status_code == 200
    assert calls == 2


async def test_retrying_http_client_does_not_retry_non_transient_401(monkeypatch) -> None:
    _fast_retry_settings(monkeypatch, attempts=3)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, request=request)

    client = _build_retrying_http_client(wrapped=httpx.MockTransport(handler))
    try:
        response = await client.get("https://provider.example/test")
    finally:
        await client.aclose()

    assert response.status_code == 401
    assert calls == 1


async def test_retrying_http_client_exhaustion_preserves_response(monkeypatch) -> None:
    _fast_retry_settings(monkeypatch, attempts=3)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, request=request)

    client = _build_retrying_http_client(wrapped=httpx.MockTransport(handler))
    try:
        response = await client.get("https://provider.example/test")
        assert response.status_code == 503
    finally:
        await client.aclose()

    assert calls == 3


@pytest.mark.parametrize("vertex", [False, True])
@pytest.mark.parametrize("attempts", [1, 3])
@pytest.mark.parametrize("status", [429, 503, 401, 403, "connection", "success"])
async def test_anthropic_sdk_retry_boundary(monkeypatch, vertex, attempts, status):
    import pydantic_ai.models
    from anthropic import AsyncAnthropicVertex
    from pydantic import SecretStr
    from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError
    from pydantic_ai.messages import ModelRequest, UserPromptPart
    from pydantic_ai.models import ModelRequestParameters

    from services.agents.models import factory
    from services.agents.models.domain import ResolvedModel

    monkeypatch.setattr(pydantic_ai.models, "ALLOW_MODEL_REQUESTS", True)
    _fast_retry_settings(monkeypatch, attempts=attempts)
    monkeypatch.setattr(settings, "ANTHROPIC_VERTEX_AI", vertex)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr("test-key"))
    calls = 0
    body = {"type": "error", "error": {"type": "rate_limit_error", "message": "private detail"}}

    def handler(request):
        nonlocal calls
        calls += 1
        if status == "connection":
            raise httpx.ConnectError("offline", request=request)
        if status == "success" and calls == attempts:
            return httpx.Response(
                200,
                json={
                    "id": "msg_test",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-sonnet-5",
                    "content": [{"type": "text", "text": "OK"}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 2, "output_tokens": 1},
                },
            )
        return httpx.Response(503 if status == "success" else status, json=body)

    async with _build_retrying_http_client(httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(factory, "retrying_http_client", lambda: client)
        if vertex:
            sdk = AsyncAnthropicVertex(
                project_id="test-project",
                region="global",
                access_token="test-token",  # noqa: S106 — offline SDK fixture
                http_client=client,
                max_retries=0,
            )
            monkeypatch.setattr(factory, "get_anthropic_vertex_client", lambda: sdk)
        model = factory.build_model(
            ResolvedModel(
                provider="anthropic",
                model="claude-sonnet-5",
                transport_model="claude-sonnet-5",
                settings={},
                max_steps=3,
                vertex_project="test-project",
                vertex_location="global",
                partner_transport="chat-completions",
            )
        )
        request = model.request(
            [ModelRequest(parts=[UserPromptPart(content="Hello")])], None, ModelRequestParameters()
        )
        if status == "success":
            response = await request
            assert response.parts[0].content == "OK"
        elif status == "connection":
            with pytest.raises(ModelAPIError) as error:
                await request
            assert not isinstance(error.value, ModelHTTPError)
        else:
            with pytest.raises(ModelHTTPError) as error:
                await request
            assert error.value.status_code == status
            assert error.value.body == body
    assert calls == (1 if status in (401, 403) else attempts)


@pytest.mark.parametrize("provider", ["openai", "azure", "xai", "google"])
@pytest.mark.parametrize("attempts", [1, 3])
async def test_other_sdk_attempt_limits(monkeypatch, provider, attempts):
    import pydantic_ai.models
    from pydantic import SecretStr
    from pydantic_ai.exceptions import ModelHTTPError
    from pydantic_ai.messages import ModelRequest, UserPromptPart
    from pydantic_ai.models import ModelRequestParameters

    from services.agents.models import factory
    from services.agents.models.domain import ResolvedModel

    monkeypatch.setattr(pydantic_ai.models, "ALLOW_MODEL_REQUESTS", True)
    _fast_retry_settings(monkeypatch, attempts=attempts)
    for name in ("OPENAI_API_KEY", "AZURE_OPENAI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.setattr(settings, name, SecretStr("test-key"))
    monkeypatch.setattr(settings, "AZURE_OPENAI_ENDPOINT", "https://azure.example.com")
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", False)
    monkeypatch.setattr(settings, "VERTEX_PARTNER_MODELS_ENABLED", True)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", "test-project")
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(429, json={"error": {"code": 429, "message": "private detail"}})

    async with _build_retrying_http_client(httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(factory, "retrying_http_client", lambda: client)
        monkeypatch.setattr(factory, "get_vertex_openai_client", lambda: client)
        model_name = "gemini-3-flash-preview" if provider == "google" else "test-model"
        model = factory.build_model(
            ResolvedModel(
                provider=provider,
                model=model_name,
                transport_model=model_name,
                settings={},
                max_steps=3,
                vertex_project="test-project",
                vertex_location="global",
                partner_transport="chat-completions",
            )
        )
        with pytest.raises(ModelHTTPError) as error:
            await model.request(
                [ModelRequest(parts=[UserPromptPart(content="Hello")])],
                None,
                ModelRequestParameters(),
            )
        assert error.value.status_code == 429
    assert calls == attempts


async def test_exhausted_stream_response_is_readable(monkeypatch):
    _fast_retry_settings(monkeypatch, attempts=2)
    streams = []

    class ErrorStream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            assert not self.closed
            yield b'{"error":"provider detail"}'

        async def aclose(self):
            self.closed = True

    def handler(request):
        stream = ErrorStream()
        streams.append(stream)
        return httpx.Response(503, stream=stream)

    async with (
        _build_retrying_http_client(httpx.MockTransport(handler)) as client,
        client.stream("GET", "https://provider.example/test") as response,
    ):
        assert streams[0].closed
        assert not streams[1].closed
        assert await response.aread() == b'{"error":"provider detail"}'
    assert all(stream.closed for stream in streams)
