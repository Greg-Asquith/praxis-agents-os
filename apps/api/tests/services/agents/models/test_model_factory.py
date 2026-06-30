# apps/api/tests/services/agents/models/test_model_factory.py

"""Factory construction and the credential seam.

Construction is offline: building a provider/model does not make network calls,
so these assert the correct Pydantic AI types and explicit credential handling.
"""

import pytest
from pydantic import SecretStr
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel

from core.settings import settings
from services.agents.models import build_model, provider_api_key
from services.agents.models.domain import ModelConfigurationError, ResolvedModel


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


def test_build_anthropic_model(monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr("sk-ant-test"))
    model = build_model(_spec("anthropic", "claude-sonnet-4-6"))
    assert isinstance(model, AnthropicModel)


def test_build_openai_model(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("sk-openai-test"))
    model = build_model(_spec("openai", "gpt-5.4-mini", settings={"temperature": 0.5}))
    assert isinstance(model, OpenAIChatModel)


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
