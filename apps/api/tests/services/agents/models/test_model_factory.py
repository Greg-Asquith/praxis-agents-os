# apps/api/tests/services/agents/models/test_model_factory.py

"""Factory construction and the credential seam.

Construction is offline: building a provider/model does not make network calls,
so these assert the correct Pydantic AI types and explicit credential handling.
"""

import pytest
from pydantic import SecretStr
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel

from core.settings import settings
from services.agents.models import build_model, provider_api_key
from services.agents.models.domain import ModelConfigurationError, ResolvedModel
from services.agents.models.utils import retrying_http_client


def _spec(provider, model, **kw):
    return ResolvedModel(
        provider=provider,
        model=model,
        settings=kw.get("settings", {}),
        max_steps=kw.get("max_steps", 20),
        azure_deployment=kw.get("azure_deployment"),
    )


def test_provider_api_key_reads_settings(monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr("sk-ant-test"))
    assert provider_api_key("anthropic") == "sk-ant-test"


def test_provider_api_key_missing_raises(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)
    with pytest.raises(ModelConfigurationError):
        provider_api_key("openai")


def test_provider_api_key_blank_raises(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("   "))
    with pytest.raises(ModelConfigurationError):
        provider_api_key("openai")


def test_build_anthropic_model(monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr("sk-ant-test"))
    model = build_model(_spec("anthropic", "claude-sonnet-4-6"))
    assert isinstance(model, AnthropicModel)
    assert model.provider.client._client is retrying_http_client()


def test_build_anthropic_model_enables_prompt_cache(monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr("sk-ant-test"))
    monkeypatch.setattr(settings, "AGENT_PROMPT_CACHE_ENABLED", True)

    model = build_model(_spec("anthropic", "claude-sonnet-4-6"))

    assert model.settings == {
        "anthropic_cache": True,
        "anthropic_cache_instructions": True,
        "anthropic_cache_tool_definitions": True,
    }


def test_build_anthropic_model_respects_agent_cache_settings(monkeypatch):
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


def test_build_anthropic_model_skips_prompt_cache_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr("sk-ant-test"))
    monkeypatch.setattr(settings, "AGENT_PROMPT_CACHE_ENABLED", False)

    model = build_model(_spec("anthropic", "claude-sonnet-4-6"))

    assert model.settings is None


def test_build_openai_model(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("sk-openai-test"))
    model = build_model(_spec("openai", "gpt-5.4-mini", settings={"temperature": 0.5}))
    assert isinstance(model, OpenAIResponsesModel)
    assert model.provider.client._client is retrying_http_client()


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


def test_build_azure_model_uses_deployment(monkeypatch):
    monkeypatch.setattr(settings, "AZURE_OPENAI_API_KEY", SecretStr("az-test"))
    monkeypatch.setattr(settings, "AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    model = build_model(_spec("azure", "gpt-5.4-mini", azure_deployment="my-deployment"))
    assert isinstance(model, OpenAIChatModel)


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


def test_build_unsupported_provider_raises():
    with pytest.raises(ModelConfigurationError):
        build_model(_spec("cohere", "command-r"))
