"""Partner transport authentication, request construction, and lifecycle."""

import asyncio
import json
from threading import get_ident
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
import sqlalchemy as sa
from google.auth.exceptions import RefreshError
from pydantic_ai import Agent
from pydantic_ai.models import override_allow_model_requests
from pydantic_ai.models.openai import OpenAIChatModel

from core.settings import settings
from models.ai_usage_event import AIUsageEvent
from services.agents.models import build_model, close_vertex_clients, vertex_openai_client as vertex
from services.agents.models.domain import ModelConfigurationError, ResolvedModel
from services.ai_usage.domain import AIUsageEventData
from services.ai_usage.record_in_transaction import record_ai_usage_in_transaction
from services.ai_usage.utils import usage_values
from tests.factories import build_workspace


@pytest.fixture
async def partner_settings(monkeypatch):
    monkeypatch.setattr(settings, "VERTEX_PARTNER_MODELS_ENABLED", True)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", "vertex-project")
    monkeypatch.setattr(settings, "VERTEX_PARTNER_LOCATION", "us-central1")
    yield
    await close_vertex_clients()


def spec(provider="meta"):
    return ResolvedModel(
        provider=provider,
        model="partner-chat",
        transport_model=f"{provider}/partner-chat",
        settings={"temperature": 0.2},
        max_steps=20,
    )


async def test_auth_loads_off_loop_and_serializes_refresh(monkeypatch):
    loop_thread = get_ident()
    credentials = SimpleNamespace(valid=False, token=None)

    def refresh(request):
        assert get_ident() != loop_thread
        credentials.token = "adc-token"
        credentials.valid = True

    credentials.refresh = Mock(side_effect=refresh)

    def load(**kwargs):
        assert get_ident() != loop_thread
        assert kwargs == {"scopes": ["https://www.googleapis.com/auth/cloud-platform"]}
        return credentials, "adc-project"

    load = Mock(side_effect=load)
    monkeypatch.setattr(vertex.google.auth, "default", load)
    headers = []

    def respond(request):
        headers.append(request.headers["Authorization"])
        return httpx.Response(200)

    async with httpx.AsyncClient(
        auth=vertex.VertexBearerAuth(), transport=httpx.MockTransport(respond)
    ) as client:
        await asyncio.gather(
            *(
                client.get("https://example.com", headers={"Authorization": "Bearer unused"})
                for _ in range(8)
            )
        )
        assert credentials.refresh.call_count == 1
        credentials.valid = False
        await client.get("https://example.com")
    load.assert_called_once()
    assert credentials.refresh.call_count == 2
    assert headers == ["Bearer adc-token"] * 9


async def test_refresh_failure_sends_no_request(monkeypatch):
    credentials = SimpleNamespace(valid=False, refresh=Mock(side_effect=RefreshError("expired")))
    monkeypatch.setattr(vertex.google.auth, "default", lambda **kwargs: (credentials, None))
    send = Mock(return_value=httpx.Response(200))
    async with httpx.AsyncClient(
        auth=vertex.VertexBearerAuth(), transport=httpx.MockTransport(send)
    ) as client:
        with pytest.raises(RefreshError):
            await client.get("https://example.com")
    send.assert_not_called()


@pytest.mark.parametrize(
    "location,host",
    [
        ("us-central1", "us-central1-aiplatform.googleapis.com"),
        ("global", "aiplatform.googleapis.com"),
    ],
)
def test_partner_base_url(location, host):
    assert vertex.partner_base_url("project", location) == (
        f"https://{host}/v1/projects/project/locations/{location}/endpoints/openapi"
    )


@pytest.mark.parametrize("provider", ["meta", "mistral", "xai"])
async def test_factory_uses_shared_chat_client(partner_settings, provider):
    model = build_model(spec(provider))
    assert isinstance(model, OpenAIChatModel)
    assert model.model_name == f"{provider}/partner-chat"
    assert model.settings == {"temperature": 0.2}
    client = vertex.get_vertex_openai_client()
    assert model.provider.client._client is client
    assert isinstance(client.auth, vertex.VertexBearerAuth)
    assert (
        str(model.provider.base_url)
        == vertex.partner_base_url("vertex-project", "us-central1") + "/"
    )
    assert build_model(spec(provider)).provider.client._client is client
    await close_vertex_clients()
    assert client.is_closed
    assert vertex.get_vertex_openai_client.cache_info().currsize == 0


@pytest.mark.parametrize("provider", ["meta", "mistral", "xai"])
def test_factory_rejects_disabled_partner(partner_settings, monkeypatch, provider):
    monkeypatch.setattr(settings, "VERTEX_PARTNER_MODELS_ENABLED", False)
    with pytest.raises(ModelConfigurationError, match="VERTEX_PARTNER_MODELS_ENABLED"):
        build_model(spec(provider))


def test_factory_rejects_missing_project(partner_settings, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", None)
    monkeypatch.setattr(settings, "GCP_PROJECT_ID", None)
    with pytest.raises(ModelConfigurationError, match="requires a project"):
        build_model(spec())


async def test_chat_request_records_partner_usage(partner_settings, monkeypatch, db_session):
    credentials = SimpleNamespace(valid=True)
    credentials.token = "adc-token"
    monkeypatch.setattr(vertex.google.auth, "default", lambda **kwargs: (credentials, None))

    def respond(request):
        assert request.headers["Authorization"] == "Bearer adc-token"
        assert request.url.path.endswith("/endpoints/openapi/chat/completions")
        assert json.loads(request.content)["model"] == "meta/partner-chat"
        return httpx.Response(
            200,
            json={
                "id": "chat-1",
                "object": "chat.completion",
                "created": 1,
                "model": "meta/partner-chat",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "Hello"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
            },
        )

    build_client = vertex._build_retrying_http_client
    monkeypatch.setattr(
        vertex,
        "_build_retrying_http_client",
        lambda **kwargs: build_client(httpx.MockTransport(respond), **kwargs),
    )
    with override_allow_model_requests(True):
        result = await Agent(build_model(spec()), name="partner_test").run("Hello")
    assert result.output == "Hello"
    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 4
    workspace = build_workspace()
    db_session.add(workspace)
    await db_session.flush()
    assert await record_ai_usage_in_transaction(
        db_session,
        AIUsageEventData(
            workspace_id=workspace.id,
            provider=spec().provider,
            model=spec().model,
            purpose="agent_run",
            **usage_values(result.usage),
        ),
    )
    event = await db_session.scalar(
        sa.select(AIUsageEvent).where(AIUsageEvent.workspace_id == workspace.id)
    )
    assert (event.provider, event.model) == ("meta", "partner-chat")
    assert (event.input_tokens, event.output_tokens, event.requests) == (12, 4, 1)
