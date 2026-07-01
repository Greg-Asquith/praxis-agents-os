# apps/api/services/agents/models/resolution.py

"""Resolve which model to run for an agent or a fixed utility use case.

Resolution is agent-driven: every agent carries its own provider/model/settings,
so delegation to a specialist agent automatically inherits that agent's model.
The only non-agent use case today is conversation naming, a settings constant.
"""

from typing import Any

from core.settings import settings
from services.agents.models.domain import (
    DEFAULT_MAX_STEPS,
    PROVIDER_AZURE,
    PROVIDER_OPENAI,
    ModelConfigurationError,
    ResolvedModel,
)
from services.agents.models.registry import get_model


def _require_active(provider: str, model: str):
    """Return the catalog entry, rejecting unknown and deprecated models."""
    info = get_model(provider, model)
    if info.deprecated:
        raise ModelConfigurationError(
            f"Model '{provider}:{model}' is deprecated and cannot be used for new runs.",
            details={"provider": provider, "model": model},
        )
    return info


def resolve_agent_model(agent) -> ResolvedModel:
    """Resolve the model for an agent, falling back to settings defaults.

    Precedence per field: the agent's own column, else the configured default.
    The agent's ``model_settings`` override the catalog defaults shallowly.
    """
    provider = agent.model_provider or settings.DEFAULT_MODEL_PROVIDER
    model = agent.model or settings.DEFAULT_MODEL

    # Azure is deployment-based: the deployment name is customer-defined and not
    # part of the Python catalog, so membership is not validated for it.
    default_settings = {} if provider == PROVIDER_AZURE else dict(_require_active(provider, model).default_settings)

    merged: dict[str, Any] = {**default_settings, **(agent.model_settings or {})}
    _apply_openai_reasoning_summary(provider, merged)
    max_steps = agent.max_steps or DEFAULT_MAX_STEPS

    return ResolvedModel(
        provider=provider,
        model=model,
        settings=merged,
        max_steps=max_steps,
        azure_deployment=agent.azure_deployment,
    )


def _apply_openai_reasoning_summary(provider: str, merged: dict[str, Any]) -> None:
    """Ask OpenAI's Responses API for a readable reasoning summary when thinking is on.

    Without this the Responses API returns only encrypted reasoning (a signature with
    empty content), so the transcript can never show real thinking. The unified
    ``thinking`` setting only controls reasoning effort, so request the summary here.
    """
    if provider != PROVIDER_OPENAI or not merged.get("thinking"):
        return
    merged.setdefault("openai_reasoning_summary", "auto")


def resolve_naming_model() -> ResolvedModel:
    """Resolve the fixed model used to generate conversation titles."""
    provider = settings.CONVERSATION_NAMING_PROVIDER
    model = settings.CONVERSATION_NAMING_MODEL
    info = _require_active(provider, model)

    return ResolvedModel(
        provider=provider,
        model=model,
        settings=dict(info.default_settings),
        max_steps=DEFAULT_MAX_STEPS,
    )
