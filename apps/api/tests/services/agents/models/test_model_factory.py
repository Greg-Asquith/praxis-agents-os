# apps/api/tests/services/agents/models/test_model_factory.py

"""Factory construction and the credential seam.

Construction is offline: building a provider/model does not make network calls,
so these assert the correct Pydantic AI types and explicit credential handling.
"""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx2 as httpx
import pytest
from anthropic import AsyncAnthropicVertex
from pydantic import SecretStr
from pydantic_ai.models import DEFAULT_HTTP_TIMEOUT
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel

from core.settings import settings
from services.agents.models import build_model, close_vertex_clients, provider_api_key
from services.agents.models.domain import (
    MissingModelCredentialError,
    ModelConfigurationError,
    ResolvedModel,
)
from services.agents.models.vertex_clients import (
    get_anthropic_vertex_client,
    get_google_vertex_client,
)


@pytest.fixture(params=[False, True], ids=["direct", "vertex"])
async def anthropic_transport(request, monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_VERTEX_AI", request.param)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", "vertex-project")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None if request.param else SecretStr("key"))
    async with httpx.AsyncClient() as http_client:
        for module_name in ("factory", "vertex_clients"):
            module = importlib.import_module(f"services.agents.models.{module_name}")
            monkeypatch.setattr(module, "retrying_http_client", lambda: http_client)
        try:
            yield request.param, http_client
        finally:
            await close_vertex_clients()


def _spec(provider, model, **kw):
    return ResolvedModel(
        provider=provider,
        model=model,
        transport_model=kw.get("transport_model", model),
        settings=kw.get("settings", {}),
        max_steps=kw.get("max_steps", 20),
        azure_deployment=kw.get("azure_deployment"),
    )


def test_provider_api_key_missing_raises(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)
    with pytest.raises(MissingModelCredentialError) as exc_info:
        provider_api_key("openai")
    assert exc_info.value.error_code == "model_provider_not_configured"
    assert exc_info.value.details == {"provider": "openai", "setting": "OPENAI_API_KEY"}


def test_build_anthropic_model_respects_agent_cache_settings(monkeypatch, anthropic_transport):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr("sk-ant-test"))
    monkeypatch.setattr(settings, "AGENT_PROMPT_CACHE_ENABLED", True)

    model = build_model(
        _spec(
            "anthropic",
            "claude-sonnet-5",
            settings={
                "anthropic_cache": "1h",
                "anthropic_cache_instructions": False,
                "temperature": 0.2,
            },
        )
    )

    assert model.settings == {
        "anthropic_cache": "1h",
        "anthropic_cache_instructions": False,
        "anthropic_cache_tool_definitions": True,
        "temperature": 0.2,
    }


def test_build_openai_model_ignores_ambient_base_url_env(monkeypatch):
    # A blank OPENAI_BASE_URL in the process env must not produce schemeless requests.
    monkeypatch.setenv("OPENAI_BASE_URL", "")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("sk-openai-test"))
    model = build_model(_spec("openai", "gpt-6-luna"))
    assert str(model.provider.client.base_url) == "https://api.openai.com/v1/"


def test_build_azure_model_requires_endpoint(monkeypatch):
    monkeypatch.setattr(settings, "AZURE_OPENAI_API_KEY", SecretStr("az-test"))
    monkeypatch.setattr(settings, "AZURE_OPENAI_ENDPOINT", None)
    with pytest.raises(ModelConfigurationError):
        build_model(_spec("azure", "gpt-6-luna", azure_deployment="my-deployment"))


@pytest.mark.parametrize(
    ("location", "host"),
    [
        ("global", "aiplatform.googleapis.com"),
        ("us", "aiplatform.us.rep.googleapis.com"),
        ("europe-west1", "europe-west1-aiplatform.googleapis.com"),
    ],
)
@pytest.mark.parametrize("explicit_project", [None, "vertex-project"])
async def test_anthropic_vertex_uses_project_location_and_transport_id(
    monkeypatch,
    location,
    host,
    explicit_project,
):
    module = importlib.import_module("services.agents.models.vertex_clients")
    monkeypatch.setattr(settings, "ANTHROPIC_VERTEX_AI", True)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", explicit_project)
    monkeypatch.setattr(settings, "GCP_PROJECT_ID", "deployment-project")
    monkeypatch.setattr(settings, "ANTHROPIC_VERTEX_LOCATION", location)
    async with httpx.AsyncClient() as http_client:
        monkeypatch.setattr(module, "retrying_http_client", lambda: http_client)
        try:
            model = build_model(
                _spec("anthropic", "catalog-alias", transport_model="claude-sonnet-5")
            )
            client = model.provider.client
            assert isinstance(model, AnthropicModel)
            assert isinstance(client, AsyncAnthropicVertex)
            assert model.model_name == "claude-sonnet-5"
            assert client.project_id == (explicit_project or "deployment-project")
            assert client.region == location
            assert str(client.base_url) == f"https://{host}/v1/"
            assert client._client is http_client
            assert client.timeout == DEFAULT_HTTP_TIMEOUT
            assert client.max_retries == 0
            assert get_anthropic_vertex_client() is client
        finally:
            await close_vertex_clients()
        assert http_client.is_closed


async def test_vertex_shutdown_closes_anthropic_after_google_close_failure(monkeypatch):
    module = importlib.import_module("services.agents.models.vertex_clients")
    google_close = AsyncMock(side_effect=RuntimeError("close failed"))
    anthropic_close = AsyncMock()
    monkeypatch.setattr(
        module,
        "Client",
        Mock(
            return_value=SimpleNamespace(
                aio=SimpleNamespace(aclose=google_close),
            )
        ),
    )
    monkeypatch.setattr(
        module,
        "AsyncAnthropicVertex",
        Mock(
            return_value=SimpleNamespace(
                close=anthropic_close,
            )
        ),
    )
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", "vertex-project")
    get_google_vertex_client()
    get_anthropic_vertex_client()
    with pytest.raises(RuntimeError, match="close failed"):
        await close_vertex_clients()
    anthropic_close.assert_awaited_once_with()
    assert not module._clients
    assert not module._anthropic_clients


@pytest.mark.parametrize(
    ("vertex_project", "gcp_project_id", "expected_project"),
    [
        ("vertex-project", "deployment-project", "vertex-project"),
        (None, "deployment-project", "deployment-project"),
    ],
)
async def test_build_google_vertex_uses_project_location_and_request_policy(
    monkeypatch,
    vertex_project,
    gcp_project_id,
    expected_project,
):
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", True)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", vertex_project)
    monkeypatch.setattr(settings, "GCP_PROJECT_ID", gcp_project_id)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_LOCATION", "us")
    monkeypatch.setattr(settings, "LLM_HTTP_RETRY_MAX_ATTEMPTS", 7)
    monkeypatch.setattr(settings, "LLM_HTTP_RETRY_MAX_WAIT_SECONDS", 23.5)

    try:
        model = build_model(_spec("google", "gemini-3.8-flash"))

        assert isinstance(model, GoogleModel)
        client = model.provider.client
        assert client.vertexai is True
        assert client._api_client.project == expected_project
        assert client._api_client.location == "us"
        http_options = client._api_client._http_options
        assert http_options.timeout == DEFAULT_HTTP_TIMEOUT * 1000
        assert http_options.retry_options is not None
        assert http_options.retry_options.attempts == 7
        assert http_options.retry_options.max_delay == 23.5
    finally:
        await close_vertex_clients()


async def test_google_vertex_clients_share_only_matching_locations(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", "vertex-project")
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_LOCATION", "auto")
    try:
        flash = get_google_vertex_client("gemini-3.8-flash")
        pro = get_google_vertex_client("gemini-3.1-pro")
        assert flash is get_google_vertex_client("gemini-3.5-flash-lite")
        assert flash is not pro
        assert get_google_vertex_client() is pro
        monkeypatch.setattr(settings, "GOOGLE_VERTEX_LOCATION", "us")
        override = get_google_vertex_client("gemini-3.8-flash")
        assert override is not flash
        assert override._api_client.location == "us"
        assert override._api_client._http_options.base_url == (
            "https://aiplatform.us.rep.googleapis.com/"
        )
    finally:
        await close_vertex_clients()
