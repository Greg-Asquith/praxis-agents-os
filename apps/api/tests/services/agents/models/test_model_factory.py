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
from anthropic import AsyncAnthropic, AsyncAnthropicVertex
from pydantic import SecretStr
from pydantic_ai.models import DEFAULT_HTTP_TIMEOUT
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel

from core.settings import settings
from services.agents.models import build_model, close_vertex_clients, provider_api_key
from services.agents.models.domain import (
    MissingModelCredentialError,
    ModelConfigurationError,
    ResolvedModel,
)
from services.agents.models.utils import retrying_http_client
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


def test_provider_api_key_reads_settings(monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr("sk-ant-test"))
    assert provider_api_key("anthropic") == "sk-ant-test"


def test_provider_api_key_missing_raises(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)
    with pytest.raises(MissingModelCredentialError) as exc_info:
        provider_api_key("openai")
    assert exc_info.value.error_code == "model_provider_not_configured"
    assert exc_info.value.details == {"provider": "openai", "setting": "OPENAI_API_KEY"}


def test_provider_api_key_blank_raises(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("   "))
    with pytest.raises(MissingModelCredentialError):
        provider_api_key("openai")


def test_build_anthropic_model(anthropic_transport):
    vertex, http_client = anthropic_transport
    model = build_model(_spec("anthropic", "claude-sonnet-4-6"))
    assert isinstance(model, AnthropicModel)
    assert model.model_name == "claude-sonnet-4-6"
    assert model.provider.client._client is http_client
    assert isinstance(model.provider.client, AsyncAnthropicVertex if vertex else AsyncAnthropic)
    assert model.provider.client.max_retries == 0
    if not vertex:
        assert model.provider.client.api_key == "key"
        assert str(model.provider.client.base_url) == "https://api.anthropic.com"


def test_build_anthropic_model_enables_prompt_cache(monkeypatch, anthropic_transport):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr("sk-ant-test"))
    monkeypatch.setattr(settings, "AGENT_PROMPT_CACHE_ENABLED", True)

    model = build_model(_spec("anthropic", "claude-sonnet-4-6"))

    assert model.settings == {
        "anthropic_cache": True,
        "anthropic_cache_instructions": True,
        "anthropic_cache_tool_definitions": True,
    }


def test_build_anthropic_model_respects_agent_cache_settings(monkeypatch, anthropic_transport):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr("sk-ant-test"))
    monkeypatch.setattr(settings, "AGENT_PROMPT_CACHE_ENABLED", True)

    model = build_model(
        _spec(
            "anthropic",
            "claude-sonnet-4-6",
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


def test_build_anthropic_model_skips_prompt_cache_when_disabled(monkeypatch, anthropic_transport):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr("sk-ant-test"))
    monkeypatch.setattr(settings, "AGENT_PROMPT_CACHE_ENABLED", False)

    model = build_model(_spec("anthropic", "claude-sonnet-4-6"))

    assert model.settings is None


def test_build_openai_model(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("sk-openai-test"))
    model = build_model(_spec("openai", "gpt-5.4-mini", settings={"temperature": 0.5}))
    assert isinstance(model, OpenAIResponsesModel)
    assert model.model_name == "gpt-5.4-mini"
    assert model.provider.client._client is retrying_http_client()


def test_build_model_uses_resolved_transport_model(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("sk-openai-test"))
    spec = ResolvedModel(
        provider="openai",
        model="catalog-alias",
        transport_model="provider-model-id",
        settings={},
        max_steps=20,
    )

    model = build_model(spec)

    assert model.model_name == "provider-model-id"


def test_build_openai_model_ignores_ambient_base_url_env(monkeypatch):
    # A blank OPENAI_BASE_URL in the process env must not produce schemeless requests.
    monkeypatch.setenv("OPENAI_BASE_URL", "")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("sk-openai-test"))
    model = build_model(_spec("openai", "gpt-5.4-mini"))
    assert str(model.provider.client.base_url) == "https://api.openai.com/v1/"


def test_openai_base_url_setting_coerces_blank_values():
    from core.settings import Settings

    assert Settings(OPENAI_BASE_URL="   ").OPENAI_BASE_URL == "https://api.openai.com/v1"
    assert Settings(OPENAI_BASE_URL=" https://proxy.example/v1 ").OPENAI_BASE_URL == (
        "https://proxy.example/v1"
    )


def test_prompt_cache_defaults_are_anthropic_only(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_PROMPT_CACHE_ENABLED", True)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("sk-openai-test"))
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", False)
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", SecretStr("g-test"))
    monkeypatch.setattr(settings, "AZURE_OPENAI_API_KEY", SecretStr("az-test"))
    monkeypatch.setattr(settings, "AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")

    models = [
        build_model(_spec("openai", "gpt-5.4-mini", settings={"temperature": 0.5})),
        build_model(_spec("google", "gemini-3.5-flash", settings={"temperature": 0.5})),
        build_model(
            _spec(
                "azure",
                "gpt-5.4-mini",
                settings={"temperature": 0.5},
                azure_deployment="my-deployment",
            )
        ),
    ]

    assert [model.settings for model in models] == [{"temperature": 0.5}] * 3


def test_build_google_model_gemini_api(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", False)
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", SecretStr("g-test"))
    model = build_model(_spec("google", "gemini-3.5-flash"))
    assert isinstance(model, GoogleModel)
    assert model.model_name == "gemini-3.5-flash"
    assert (
        model.provider.client._api_client._http_options.httpx_async_client is retrying_http_client()
    )


def test_build_azure_model_uses_deployment(monkeypatch):
    monkeypatch.setattr(settings, "AZURE_OPENAI_API_KEY", SecretStr("az-test"))
    monkeypatch.setattr(settings, "AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    model = build_model(_spec("azure", "gpt-5.4-mini", azure_deployment="my-deployment"))
    assert isinstance(model, OpenAIChatModel)
    assert model.model_name == "my-deployment"


def test_build_azure_model_uses_transport_model_without_deployment(monkeypatch):
    monkeypatch.setattr(settings, "AZURE_OPENAI_API_KEY", SecretStr("az-test"))
    monkeypatch.setattr(settings, "AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")

    model = build_model(
        _spec(
            "azure",
            "catalog-alias",
            transport_model="provider-model-id",
        )
    )

    assert isinstance(model, OpenAIChatModel)
    assert model.model_name == "provider-model-id"


def test_build_azure_model_requires_endpoint(monkeypatch):
    monkeypatch.setattr(settings, "AZURE_OPENAI_API_KEY", SecretStr("az-test"))
    monkeypatch.setattr(settings, "AZURE_OPENAI_ENDPOINT", None)
    with pytest.raises(ModelConfigurationError):
        build_model(_spec("azure", "gpt-5.4-mini", azure_deployment="my-deployment"))


def test_build_google_vertex_requires_project(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", True)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", None)
    monkeypatch.setattr(settings, "GCP_PROJECT_ID", None)
    with pytest.raises(ModelConfigurationError):
        build_model(_spec("google", "gemini-3.1-pro"))


def test_build_anthropic_vertex_requires_project(monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_VERTEX_AI", True)
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr("unused-direct-key"))
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", None)
    monkeypatch.setattr(settings, "GCP_PROJECT_ID", None)
    with pytest.raises(ModelConfigurationError, match="requires a project") as exc_info:
        build_model(_spec("anthropic", "claude-sonnet-4-6"))
    assert exc_info.value.details == {"provider": "anthropic"}


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
                _spec("anthropic", "catalog-alias", transport_model="claude-sonnet-4-6")
            )
            client = model.provider.client
            assert isinstance(model, AnthropicModel)
            assert isinstance(client, AsyncAnthropicVertex)
            assert model.model_name == "claude-sonnet-4-6"
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


@pytest.mark.parametrize(
    ("setting", "changed_value"),
    [
        ("GOOGLE_VERTEX_PROJECT", "another-project"),
        ("ANTHROPIC_VERTEX_LOCATION", "us"),
        ("LLM_HTTP_RETRY_MAX_ATTEMPTS", 7),
        ("LLM_HTTP_RETRY_MAX_WAIT_SECONDS", 23.5),
    ],
)
async def test_anthropic_vertex_clients_share_stable_configuration_and_close_all(
    monkeypatch,
    setting,
    changed_value,
):
    module = importlib.import_module("services.agents.models.vertex_clients")
    clients = [SimpleNamespace(close=AsyncMock()), SimpleNamespace(close=AsyncMock())]
    constructor = Mock(side_effect=clients)
    monkeypatch.setattr(module, "AsyncAnthropicVertex", constructor)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", "vertex-project")
    monkeypatch.setattr(settings, "ANTHROPIC_VERTEX_LOCATION", "global")
    monkeypatch.setattr(settings, "LLM_HTTP_RETRY_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(settings, "LLM_HTTP_RETRY_MAX_WAIT_SECONDS", 10.0)

    first = get_anthropic_vertex_client()
    assert get_anthropic_vertex_client() is first
    monkeypatch.setattr(settings, setting, changed_value)
    assert get_anthropic_vertex_client() is clients[1]
    assert constructor.call_count == 2
    await close_vertex_clients()
    await close_vertex_clients()
    for client in clients:
        client.close.assert_awaited_once_with()
    assert not module._anthropic_clients


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
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_LOCATION", "europe-west3")
    monkeypatch.setattr(settings, "LLM_HTTP_RETRY_MAX_ATTEMPTS", 7)
    monkeypatch.setattr(settings, "LLM_HTTP_RETRY_MAX_WAIT_SECONDS", 23.5)

    try:
        model = build_model(_spec("google", "gemini-3.5-flash"))

        assert isinstance(model, GoogleModel)
        client = model.provider.client
        assert client.vertexai is True
        assert client._api_client.project == expected_project
        assert client._api_client.location == "europe-west3"
        http_options = client._api_client._http_options
        assert http_options.timeout == DEFAULT_HTTP_TIMEOUT * 1000
        assert http_options.retry_options is not None
        assert http_options.retry_options.attempts == 7
        assert http_options.retry_options.max_delay == 23.5
    finally:
        await close_vertex_clients()


async def test_google_vertex_client_is_process_shared_and_closed(monkeypatch) -> None:
    vertex_client_module = importlib.import_module("services.agents.models.vertex_clients")
    close = AsyncMock()
    client = SimpleNamespace(aio=SimpleNamespace(aclose=close))
    construct_client = Mock(return_value=client)

    monkeypatch.setattr(vertex_client_module, "Client", construct_client)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", True)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", "vertex-project")

    first = get_google_vertex_client()
    second = get_google_vertex_client()
    await close_vertex_clients()

    assert first is client
    assert second is client
    construct_client.assert_called_once()
    close.assert_awaited_once_with()


def test_build_unsupported_provider_raises():
    with pytest.raises(ModelConfigurationError):
        build_model(_spec("cohere", "command-r"))


@pytest.mark.parametrize(
    "model,location",
    [
        ("gemini-3.8-flash", "eu"),
        ("gemini-3.7-flash", "eu"),
        ("gemini-3.6-flash", "eu"),
        ("gemini-3.5-flash", "eu"),
        ("gemini-3.5-flash-lite", "eu"),
        ("gemini-3.1-flash-lite", "eu"),
        ("gemini-3.1-pro", "global"),
    ],
)
async def test_google_vertex_automatic_model_location(monkeypatch, model, location):
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", True)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", "vertex-project")
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_LOCATION", "auto")
    try:
        client = build_model(_spec("google", model)).provider.client
        assert client._api_client.location == location
        expected_host = (
            "https://aiplatform.eu.rep.googleapis.com/"
            if location == "eu"
            else "https://aiplatform.googleapis.com/"
        )
        assert client._api_client._http_options.base_url == expected_host
        assert settings.GOOGLE_VERTEX_LOCATION == "auto"
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


@pytest.mark.parametrize(
    "model,location",
    [("gemini-3.1-pro", "eu"), ("gemini-3.8-flash", "europe-west4")],
)
def test_google_vertex_rejects_unsupported_location(monkeypatch, model, location):
    vertex_client_module = importlib.import_module("services.agents.models.vertex_clients")
    constructor = Mock()
    monkeypatch.setattr(vertex_client_module, "Client", constructor)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", "vertex-project")
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_LOCATION", location)
    with pytest.raises(ModelConfigurationError, match="Unsupported Vertex AI location"):
        get_google_vertex_client(model)
    constructor.assert_not_called()
