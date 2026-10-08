# apps/api/tests/services/agents/runtime/test_subagent_model.py

"""Sub-agent model choice never ranks above the parent's model."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from core.settings import settings
from models.agent import Agent
from services.agents.runtime.subagents.build_subagent import build_subagent
from services.agents.runtime.subagents.resolve_subagent_model import resolve_subagent_model
from services.agents.runtime.subagents.spec import SubagentSpec


def _parent(provider: str, model: str) -> SimpleNamespace:
    return SimpleNamespace(
        model_provider=provider,
        model=model,
        model_settings=None,
        max_steps=None,
        azure_deployment=None,
    )


@pytest.mark.parametrize(
    ("parent_model", "tier", "expected"),
    [
        ("claude-opus-5-5", "light", ("anthropic", "claude-haiku-5-5")),
        ("claude-opus-5-5", "max", ("anthropic", "claude-opus-5-5")),
        ("claude-haiku-4-5", None, ("anthropic", "claude-haiku-4-5")),
    ],
    ids=["lower-tier", "tier-above-parent", "default-above-parent"],
)
def test_subagent_model_resolves_within_parent_tier(monkeypatch, parent_model, tier, expected):
    monkeypatch.setattr(settings, "DEFAULT_MODEL_PROVIDER", "openai")
    monkeypatch.setattr(settings, "DEFAULT_MODEL", "gpt-6-luna")

    resolved = resolve_subagent_model(
        _parent("anthropic", parent_model), workspace=None, model_tier=tier
    )

    assert resolved == expected


@pytest.mark.parametrize(
    ("child_model", "expected_settings"),
    [("gpt-6-luna", {"thinking": True}), ("gpt-6-sol", None)],
    ids=["same-effective-model", "different-model"],
)
def test_subagent_keeps_model_settings_only_for_the_parents_effective_model(
    child_model, expected_settings
):
    parent = Agent(
        id=uuid4(),
        workspace_id=uuid4(),
        model_provider=None,
        model=None,
        model_settings={"thinking": True},
    )
    workspace = SimpleNamespace(default_model_provider="openai", default_model="gpt-6-luna")
    spec = SubagentSpec(
        role="Researcher", instructions="Research.", model_provider="openai", model=child_model
    )

    subagent = build_subagent(parent, spec, workspace=workspace)

    assert (subagent.model_provider, subagent.model) == ("openai", child_model)
    assert subagent.model_settings == expected_settings
