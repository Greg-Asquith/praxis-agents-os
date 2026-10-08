# apps/api/tests/services/agents/models/test_model_resolution.py

"""Model resolution: settings merge and provider-specific reasoning wiring.

Resolution is offline and agent-driven. These cover the OpenAI Responses reasoning
summary seam, which is what makes real thinking text reach the transcript.
"""

from types import SimpleNamespace

import pytest

from core.settings import settings
from services.agents.models import resolution
from services.agents.models.domain import ModelConfigurationError, ModelInfo
from services.agents.models.registry import get_model
from services.agents.models.resolution import resolve_agent_model
from services.agents.models.utils import is_model_available


def _agent(provider, model, **kw):
    return SimpleNamespace(
        model_provider=provider,
        model=model,
        model_settings=kw.get("model_settings"),
        max_steps=kw.get("max_steps"),
        azure_deployment=kw.get("azure_deployment"),
    )


def test_openai_thinking_requests_reasoning_summary():
    resolved = resolve_agent_model(
        _agent("openai", "gpt-6-luna", model_settings={"thinking": "high"}), workspace=None
    )
    assert resolved.settings["openai_reasoning_summary"] == "auto"


@pytest.mark.parametrize(
    ("resolver", "missing_id"),
    [
        (
            lambda: resolution.resolve_agent_model(
                _agent("anthropic", "claude-sonnet-5"), workspace=None
            ),
            None,
        ),
        (
            lambda: resolution.require_helper_model(
                provider="anthropic",
                model="claude-sonnet-5",
                supported=("anthropic",),
                defaults={"anthropic": "claude-sonnet-5"},
                tool_name="web_search",
            ),
            "",
        ),
        (resolution.resolve_naming_model, "   "),
        (resolution.resolve_history_summary_model, None),
    ],
)
def test_vertex_resolution_fails_closed_without_transport_model(
    monkeypatch: pytest.MonkeyPatch,
    resolver,
    missing_id: str | None,
) -> None:
    monkeypatch.setattr(settings, "ANTHROPIC_VERTEX_AI", True)
    monkeypatch.setattr(settings, "CONVERSATION_NAMING_PROVIDER", "anthropic")
    monkeypatch.setattr(settings, "CONVERSATION_NAMING_MODEL", "claude-sonnet-5")
    monkeypatch.setattr(settings, "AGENT_HISTORY_SUMMARY_MODEL_PROVIDER", "anthropic")
    monkeypatch.setattr(settings, "AGENT_HISTORY_SUMMARY_MODEL", "claude-sonnet-5")
    info = ModelInfo(
        provider="anthropic",
        model="claude-sonnet-5",
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
        "model": "claude-sonnet-5",
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
    monkeypatch.setattr(settings, "VERTEX_PARTNER_MODELS", [f"meta:{alias}"])
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", "vertex-project")
    resolved = resolution.resolve_agent_model(_agent("meta", alias), workspace=None)
    assert resolved.model == alias
    assert resolved.transport_model == transport_id


def test_vertex_model_list_limits_anthropic_models_and_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ANTHROPIC_VERTEX_AI", True)
    monkeypatch.setattr(settings, "ANTHROPIC_VERTEX_MODELS", ["claude-haiku-5-5"])
    monkeypatch.setattr(settings, "GOOGLE_VERTEX_PROJECT", "vertex-project")

    assert resolution.resolve_catalog_model("anthropic", "claude-haiku-5-5").transport_model == (
        "claude-haiku-5-5"
    )
    assert not is_model_available(get_model("anthropic", "claude-opus-5-5"))
    with pytest.raises(ModelConfigurationError, match="not enabled"):
        resolve_agent_model(_agent("anthropic", "claude-opus-5-5"), workspace=None)
    assert resolution.has_available_helper_model("anthropic", {"anthropic": "claude-haiku-5-5"})
    assert not resolution.has_available_helper_model("anthropic", {"anthropic": "claude-sonnet-5"})
