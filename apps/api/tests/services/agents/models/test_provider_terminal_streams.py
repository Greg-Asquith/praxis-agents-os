"""Qualifies provider terminal responses through the configured adapters."""

import json

import httpx2 as httpx
import pytest
from pydantic import SecretStr
from pydantic_ai import models
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models import ModelRequestParameters

from core.settings import settings
from services.agents.models import factory
from services.agents.models.domain import ResolvedModel


@pytest.mark.parametrize(
    ("status", "reason", "expected"),
    [
        ("completed", None, "stop"),
        ("incomplete", "max_output_tokens", "length"),
        ("incomplete", "content_filter", "content_filter"),
        ("failed", None, "error"),
    ],
)
async def test_responses_stream_preserves_terminal_reason(monkeypatch, status, reason, expected):
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("test-key"))
    response = {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "model": "gpt-5.4-mini",
        "status": status,
        "output": [],
        "incomplete_details": {"reason": reason} if reason else None,
        "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
    }
    events = [
        {"type": "response.created", "response": {**response, "status": "in_progress"}},
        {
            "type": "response.output_text.delta",
            "item_id": "msg_test",
            "output_index": 0,
            "content_index": 0,
            "delta": "Result",
        },
        {"type": f"response.{status}", "response": response},
    ]
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text="".join(f"data: {json.dumps(event)}\n\n" for event in events),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(factory, "retrying_http_client", lambda: client)
        model = factory.build_model(
            ResolvedModel(
                provider="openai",
                model="gpt-5.4-mini",
                transport_model="gpt-5.4-mini",
                settings={},
                max_steps=3,
            )
        )
        async with model.request_stream(
            [ModelRequest(parts=[UserPromptPart("Hello")])], None, ModelRequestParameters()
        ) as stream:
            async for _event in stream:
                pass
            result = stream.get()

    assert len(requests) == 1
    assert requests[0].url.path == "/v1/responses"
    assert result.finish_reason == expected
    assert result.provider_details["finish_reason"] == (reason or status)
    assert result.usage.input_tokens == 3
    assert result.usage.output_tokens == 2


async def test_azure_content_filter_error_becomes_filtered_response(monkeypatch):
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", True)
    monkeypatch.setattr(settings, "AZURE_OPENAI_API_KEY", SecretStr("test-key"))
    monkeypatch.setattr(settings, "AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(400, json={"error": {"code": "content_filter", "message": "Blocked"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        monkeypatch.setattr(factory, "retrying_http_client", lambda: client)
        model = factory.build_model(
            ResolvedModel(
                provider="azure",
                model="gpt-5.4-mini",
                transport_model="gpt-5.4-mini",
                azure_deployment="test-deployment",
                settings={},
                max_steps=3,
            )
        )
        messages = [ModelRequest(parts=[UserPromptPart("Hello")])]
        result = await model.request(messages, None, ModelRequestParameters())

    assert len(requests) == 1
    assert result.finish_reason == "content_filter"
    assert result.parts == []
    assert result.provider_details == {"finish_reason": "content_filter"}
