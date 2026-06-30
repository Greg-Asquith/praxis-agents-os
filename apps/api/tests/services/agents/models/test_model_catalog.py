# apps/api/tests/services/agents/models/test_model_catalog.py

"""Registry lookups and agent/naming model resolution.

Pure unit tests: no database, no network, no provider construction.
"""

from types import SimpleNamespace

import pytest

from core.settings import settings
from services.agents.models import (
    get_model,
    is_known,
    list_models,
    qualified_id,
    resolve_agent_model,
    resolve_naming_model,
)
from services.agents.models.domain import DEFAULT_MAX_STEPS, ModelConfigurationError


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


def test_get_model_returns_entry_with_qualified_id():
    info = get_model("openai", "gpt-5.4-mini")
    assert info.provider == "openai"
    assert info.qualified_id == "openai:gpt-5.4-mini"


def test_get_model_unknown_raises():
    with pytest.raises(ModelConfigurationError):
        get_model("openai", "does-not-exist")


def test_is_known_distinguishes_membership():
    assert is_known("anthropic", "claude-sonnet-4-6")
    assert not is_known("anthropic", "claude-imaginary")


def test_qualified_id_validates_membership():
    assert qualified_id("google", "gemini-3.1-pro") == "google:gemini-3.1-pro"
    with pytest.raises(ModelConfigurationError):
        qualified_id("google", "gemini-unknown")


def test_list_models_excludes_deprecated_by_default():
    visible = list_models()
    all_models = list_models(include_deprecated=True)
    assert all(not m.deprecated for m in visible)
    assert {m.qualified_id for m in visible} <= {m.qualified_id for m in all_models}


# Resolution


def test_resolve_agent_model_uses_agent_columns():
    agent = _agent(
        model_provider="anthropic",
        model="claude-opus-4-8",
        model_settings={"temperature": 0.2},
        max_steps=7,
    )
    resolved = resolve_agent_model(agent)
    assert resolved.qualified_id == "anthropic:claude-opus-4-8"
    assert resolved.settings["temperature"] == 0.2
    assert resolved.max_steps == 7


def test_resolve_agent_model_falls_back_to_settings_defaults():
    resolved = resolve_agent_model(_agent())
    assert resolved.provider == settings.DEFAULT_MODEL_PROVIDER
    assert resolved.model == settings.DEFAULT_MODEL
    assert resolved.max_steps == DEFAULT_MAX_STEPS


def test_resolve_agent_model_rejects_unknown_model():
    with pytest.raises(ModelConfigurationError):
        resolve_agent_model(_agent(model_provider="anthropic", model="claude-nope"))


def test_resolve_agent_model_azure_skips_catalog_membership():
    agent = _agent(
        model_provider="azure",
        model="gpt-5.4-mini",
        azure_deployment="my-deployment",
        model_settings={"temperature": 0.3},
    )
    resolved = resolve_agent_model(agent)
    assert resolved.provider == "azure"
    assert resolved.azure_deployment == "my-deployment"
    assert resolved.settings["temperature"] == 0.3


def test_resolve_naming_model_returns_configured_model():
    resolved = resolve_naming_model()
    assert resolved.provider == settings.CONVERSATION_NAMING_PROVIDER
    assert resolved.model == settings.CONVERSATION_NAMING_MODEL
