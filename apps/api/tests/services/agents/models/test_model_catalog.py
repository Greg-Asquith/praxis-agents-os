# apps/api/tests/services/agents/models/test_model_catalog.py

"""Registry lookups and agent/naming model resolution.

Pure unit tests: no database, no network, no provider construction.
"""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from core.settings import settings
from services.agents.models import (
    get_model,
    list_model_catalog,
    list_models,
    registry as model_registry,
    resolve_agent_model,
    resolve_model_context_budget,
)
from services.agents.models.domain import (
    DEFAULT_MAX_STEPS,
    PROVIDER_ANTHROPIC,
    PROVIDER_GOOGLE,
    PROVIDER_META,
    PROVIDER_MISTRAL,
    PROVIDER_OPENAI,
    PROVIDER_XAI,
    ModelConfigurationError,
)


def _agent(**overrides):
    """A minimal Agent stand-in carrying only the columns resolution reads."""
    base = {
        "model_provider": None,
        "model": None,
        "model_settings": None,
        "azure_deployment": None,
        "max_steps": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# Registry


# Catalog route payload


def test_model_catalog_only_lists_models_for_configured_api_key_providers(monkeypatch):
    _clear_model_provider_settings(monkeypatch)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("sk-test"))
    monkeypatch.setattr(settings, "DEFAULT_MODEL_PROVIDER", PROVIDER_OPENAI)
    monkeypatch.setattr(settings, "DEFAULT_MODEL", "gpt-6-luna")

    response = list_model_catalog()

    assert {model.provider for model in response.models} == {PROVIDER_OPENAI}
    assert {model.id for model in response.models} == {
        model.qualified_id for model in list_models() if model.provider == PROVIDER_OPENAI
    }
    assert response.defaults.agent_model == "openai:gpt-6-luna"

    providers = {provider.provider: provider for provider in response.providers}
    assert providers[PROVIDER_OPENAI].configured is True
    assert providers[PROVIDER_OPENAI].transport == "direct"
    assert providers[PROVIDER_OPENAI].model_count == len(response.models)
    assert providers[PROVIDER_OPENAI].model_type_defaults == {
        "max": "openai:gpt-6-astra",
        "powerful": "openai:gpt-6.1-sol",
        "standard": "openai:gpt-6-luna",
    }
    assert providers[PROVIDER_ANTHROPIC].configured is False
    assert providers[PROVIDER_ANTHROPIC].model_type_defaults == {}
    assert providers[PROVIDER_GOOGLE].configured is False
    assert providers[PROVIDER_META].display_name == "Meta"
    assert providers[PROVIDER_MISTRAL].display_name == "Mistral AI"
    assert providers[PROVIDER_XAI].display_name == "xAI"
    assert providers[PROVIDER_META].transport == "google-cloud"
    assert all(model.model_type for model in response.models)


def test_model_catalog_treats_blank_api_keys_as_unconfigured(monkeypatch):
    _clear_model_provider_settings(monkeypatch)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("   "))
    monkeypatch.setattr(settings, "DEFAULT_MODEL_PROVIDER", PROVIDER_OPENAI)
    monkeypatch.setattr(settings, "DEFAULT_MODEL", "gpt-6-luna")

    response = list_model_catalog()

    assert response.models == []
    assert response.defaults.agent_model is None
    providers = {provider.provider: provider for provider in response.providers}
    assert providers[PROVIDER_OPENAI].configured is False


def test_model_catalog_excludes_deprecated_models_from_type_defaults(monkeypatch):
    _clear_model_provider_settings(monkeypatch)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", SecretStr("sk-test"))
    models = list_models()
    newest_powerful = next(
        model
        for model in models
        if model.provider == PROVIDER_OPENAI and model.model_type == "powerful"
    )
    catalog_with_deprecation = tuple(
        replace(model, deprecated=True) if model == newest_powerful else model for model in models
    )
    monkeypatch.setattr(model_registry, "_CATALOG", catalog_with_deprecation)

    response = list_model_catalog()
    providers = {provider.provider: provider for provider in response.providers}

    assert newest_powerful.qualified_id not in {model.id for model in response.models}
    assert providers[PROVIDER_OPENAI].model_type_defaults["powerful"] == "openai:gpt-6-sol"


# Resolution


def test_resolve_agent_model_uses_agent_columns():
    agent = _agent(
        model_provider="anthropic",
        model="claude-fable-5",
        model_settings={"temperature": 0.2},
        max_steps=7,
    )
    resolved = resolve_agent_model(agent, workspace=None)
    assert resolved.qualified_id == "anthropic:claude-fable-5"
    assert resolved.settings["temperature"] == 0.2
    assert resolved.max_steps == 7


def test_resolve_agent_model_prefers_workspace_default_over_settings_default():
    workspace = SimpleNamespace(default_model_provider="anthropic", default_model="claude-sonnet-5")
    resolved = resolve_agent_model(_agent(), workspace=workspace)
    assert resolved.qualified_id == "anthropic:claude-sonnet-5"
    assert resolved.max_steps == DEFAULT_MAX_STEPS

    fallback = resolve_agent_model(_agent(), workspace=None)
    assert fallback.provider == settings.DEFAULT_MODEL_PROVIDER
    assert fallback.model == settings.DEFAULT_MODEL


def test_resolve_agent_model_rejects_unknown_model():
    with pytest.raises(ModelConfigurationError):
        resolve_agent_model(_agent(model_provider="anthropic", model="claude-nope"), workspace=None)


def test_azure_context_budget_uses_explicit_deployment_settings(monkeypatch):
    monkeypatch.setattr(settings, "AZURE_OPENAI_CONTEXT_WINDOW", 256_000)
    monkeypatch.setattr(settings, "AZURE_OPENAI_CHARS_PER_TOKEN", 3.5)
    resolved = resolve_agent_model(
        _agent(
            model_provider="azure",
            model="gpt-6-luna",
            azure_deployment="my-deployment",
        ),
        workspace=None,
    )

    budget = resolve_model_context_budget(resolved)

    assert budget.context_window == 256_000
    assert budget.chars_per_token == 3.5


def test_catalog_context_budget_uses_model_calibration():
    resolved = resolve_agent_model(
        _agent(model_provider="openai", model="gpt-6-luna"), workspace=None
    )

    budget = resolve_model_context_budget(resolved)

    assert budget.context_window == get_model("openai", "gpt-6-luna").context_window
    assert budget.chars_per_token == get_model("openai", "gpt-6-luna").chars_per_token


def _clear_model_provider_settings(monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", False)
    monkeypatch.setattr(settings, "ANTHROPIC_VERTEX_AI", False)
    monkeypatch.setattr(settings, "VERTEX_PARTNER_MODELS_ENABLED", False)
    monkeypatch.setattr(settings, "VERTEX_PARTNER_MODELS", [])
    monkeypatch.setattr(settings, "ANTHROPIC_VERTEX_MODELS", [])
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", None)
    monkeypatch.setattr(settings, "GCP_PROJECT_ID", None)
    monkeypatch.setattr(settings, "AZURE_OPENAI_API_KEY", None)
    monkeypatch.setattr(settings, "AZURE_OPENAI_ENDPOINT", None)
