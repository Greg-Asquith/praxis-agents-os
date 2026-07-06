# apps/api/tests/services/agents/models/test_model_resolution.py

"""Model resolution: settings merge and provider-specific reasoning wiring.

Resolution is offline and agent-driven. These cover the OpenAI Responses reasoning
summary seam, which is what makes real thinking text reach the transcript.
"""

from types import SimpleNamespace

from services.agents.models.resolution import resolve_agent_model


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
