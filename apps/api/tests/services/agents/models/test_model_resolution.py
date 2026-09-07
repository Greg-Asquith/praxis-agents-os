# apps/api/tests/services/agents/models/test_model_resolution.py

"""Model resolution: settings merge and provider-specific reasoning wiring.

Resolution is offline and agent-driven. These cover the OpenAI Responses reasoning
summary seam, which is what makes real thinking text reach the transcript.
"""

from inspect import Parameter, signature
from types import SimpleNamespace

import pytest

from core.settings import settings
from services.agents.models import resolution
from services.agents.models.domain import ModelConfigurationError, ModelInfo, ResolvedModel
from services.agents.models.resolution import resolve_agent_model


def _agent(provider, model, **kw):
    return SimpleNamespace(
        model_provider=provider,
        model=model,
        model_settings=kw.get("model_settings"),
        max_steps=kw.get("max_steps"),
        azure_deployment=kw.get("azure_deployment"),
    )


def test_resolved_model_requires_provider_facing_model_id() -> None:
    assert signature(ResolvedModel).parameters["transport_model"].default is Parameter.empty


@pytest.mark.parametrize("variant", ["reasoning", "non-reasoning"])
def test_grok_resolution_retains_catalog_alias(variant):
    resolved = resolve_agent_model(_agent("xai", f"grok-4-20-{variant}"))
    assert resolved.qualified_id == f"xai:grok-4-20-{variant}"
    assert resolved.transport_model == f"xai/grok-4.20-{variant}"


def test_openai_thinking_requests_reasoning_summary():
    resolved = resolve_agent_model(
        _agent("openai", "gpt-5.4-mini", model_settings={"thinking": "high"})
    )
    assert resolved.settings["openai_reasoning_summary"] == "auto"


def test_openai_without_thinking_leaves_summary_unset():
    resolved = resolve_agent_model(
        _agent("openai", "gpt-5.4-mini", model_settings={"temperature": 0.4})
    )
    assert "openai_reasoning_summary" not in resolved.settings


def test_openai_respects_explicit_summary():
    resolved = resolve_agent_model(
        _agent(
            "openai",
            "gpt-5.4-mini",
            model_settings={"thinking": "high", "openai_reasoning_summary": "detailed"},
        )
    )
    assert resolved.settings["openai_reasoning_summary"] == "detailed"


def test_non_openai_thinking_does_not_get_openai_summary():
    resolved = resolve_agent_model(
        _agent("anthropic", "claude-sonnet-4-6", model_settings={"thinking": True})
    )
    assert "openai_reasoning_summary" not in resolved.settings


@pytest.mark.parametrize(
    ("provider", "model"),
    [
        ("anthropic", "claude-sonnet-4-6"),
        ("google", "gemini-3.5-flash"),
        ("openai", "gpt-5.4-mini"),
    ],
)
def test_direct_resolution_uses_catalog_model_as_transport_model(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    model: str,
) -> None:
    monkeypatch.setattr(settings, "ANTHROPIC_VERTEX_AI", False)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", False)

    resolved = resolve_agent_model(_agent(provider, model))

    assert resolved.transport_model == model


def test_google_vertex_resolution_uses_catalog_transport_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_AI", True)

    resolved = resolve_agent_model(_agent("google", "gemini-3.1-pro"))

    assert resolved.transport_model == "gemini-3.1-pro-preview"


@pytest.mark.parametrize(
    "resolver",
    [
        lambda: resolution.resolve_agent_model(_agent("anthropic", "claude-sonnet-4-6")),
        lambda: resolution.require_helper_model(
            provider="anthropic",
            model="claude-sonnet-4-6",
            supported=("anthropic",),
            defaults={"anthropic": "claude-sonnet-4-6"},
            tool_name="web_search",
        ),
        resolution.resolve_naming_model,
        resolution.resolve_history_summary_model,
    ],
)
@pytest.mark.parametrize("missing_id", [None, "", "   "])
def test_vertex_resolution_fails_closed_without_transport_model(
    monkeypatch: pytest.MonkeyPatch,
    resolver,
    missing_id: str | None,
) -> None:
    monkeypatch.setattr(settings, "ANTHROPIC_VERTEX_AI", True)
    monkeypatch.setattr(settings, "CONVERSATION_NAMING_PROVIDER", "anthropic")
    monkeypatch.setattr(settings, "CONVERSATION_NAMING_MODEL", "claude-sonnet-4-6")
    monkeypatch.setattr(settings, "AGENT_HISTORY_SUMMARY_MODEL_PROVIDER", "anthropic")
    monkeypatch.setattr(settings, "AGENT_HISTORY_SUMMARY_MODEL", "claude-sonnet-4-6")
    info = ModelInfo(
        provider="anthropic",
        model="claude-sonnet-4-6",
        display_name="Claude Sonnet 4.6",
        context_window=1_000_000,
        model_type="standard",
        vertex_model=missing_id,
    )
    monkeypatch.setattr(resolution, "_require_active", lambda _provider, _model: info)

    with pytest.raises(ModelConfigurationError) as exc_info:
        resolver()

    assert exc_info.value.details == {
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "setting": "vertex_model",
    }


@pytest.mark.parametrize(
    ("alias", "transport_id"),
    [
        ("llama-4-maverick", "meta/llama-4-maverick-17b-128e-instruct-maas"),
        ("llama-4-scout", "meta/llama-4-scout-17b-16e-instruct-maas"),
    ],
)
def test_partner_resolution_carries_catalog_transport_model(
    monkeypatch: pytest.MonkeyPatch, alias: str, transport_id: str
) -> None:
    monkeypatch.setattr(settings, "VERTEX_PARTNER_MODELS_ENABLED", True)
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", "vertex-project")
    resolved = resolution.resolve_agent_model(_agent("meta", alias))
    assert resolved.model == alias
    assert resolved.transport_model == transport_id
