# apps/api/services/agents/models/resolution.py

"""Resolve which model to run for an agent or a fixed utility use case.

Resolution is agent-driven: every agent carries its own provider/model/settings,
so delegation to a specialist agent automatically inherits that agent's model.
Non-agent utility models, such as conversation naming and native helper tools,
resolve from settings-owned constants.
"""

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from pydantic_ai import ModelRetry

from core.settings import settings
from services.agents.models.domain import (
    DEFAULT_MAX_STEPS,
    PROVIDER_AZURE,
    PROVIDER_OPENAI,
    ModelConfigurationError,
    ModelContextBudget,
    ResolvedModel,
)
from services.agents.models.registry import find_model, get_model
from services.agents.models.utils import has_provider_api_key


def _require_active(provider: str, model: str):
    """Return the catalog entry, rejecting unknown and deprecated models."""
    info = get_model(provider, model)
    if info.deprecated:
        raise ModelConfigurationError(
            f"Model '{provider}:{model}' is deprecated and cannot be used for new runs.",
            details={"provider": provider, "model": model},
        )
    return info


def configured_helper_providers(
    supported: Sequence[str],
    *,
    is_configured: Callable[[str], bool] = has_provider_api_key,
) -> tuple[str, ...]:
    """Returns configured helper providers from a caller-owned ordered allowlist.

    The caller keeps provider-specific eligibility policy by supplying the
    allowlist and, when needed, its credential predicate.
    """
    return tuple(provider for provider in supported if is_configured(provider))


def format_provider_list(providers: Sequence[str]) -> str:
    """Formats provider names for registered tool descriptions and errors."""
    if not providers:
        return "none"
    if len(providers) == 1:
        return providers[0]
    if len(providers) == 2:
        return " and ".join(providers)
    return f"{', '.join(providers[:-1])}, and {providers[-1]}"


def require_configured_provider(
    provider: str,
    *,
    configured: Sequence[str],
    supported: Sequence[str],
    tool_name: str,
) -> None:
    """Requires a provider configured for one caller-owned helper policy."""
    if provider in supported and provider in configured:
        return
    if not configured:
        raise ModelRetry(f"No native {tool_name} providers are configured.")
    raise ModelRetry(
        f"Provider '{provider}' is not configured for native {tool_name}. "
        f"Available configured providers: {', '.join(configured)}."
    )


def require_helper_model(
    *,
    provider: str,
    model: str | None,
    supported: Sequence[str],
    defaults: Mapping[str, str],
    tool_name: str,
    require_structured_output: bool = False,
) -> ResolvedModel:
    """Resolves an active catalog model without encoding helper selection policy.

    Callers retain configured-provider checks, agent-model inheritance, fixed
    provider pins, and settings-owned request limits.
    """
    normalized_provider = provider.strip().lower()
    normalized_model = model.strip() if model is not None else None
    if normalized_provider not in supported:
        raise ModelRetry(f"Provider '{normalized_provider}' does not support native {tool_name}.")
    resolved_model = normalized_model or defaults.get(normalized_provider)
    if resolved_model is None:
        raise ModelRetry(f"Provider '{normalized_provider}' does not support native {tool_name}.")

    try:
        info = _require_active(normalized_provider, resolved_model)
    except ModelConfigurationError as exc:
        if find_model(normalized_provider, resolved_model) is not None:
            raise ModelRetry(
                f"Model '{normalized_provider}:{resolved_model}' is deprecated."
            ) from exc
        raise ModelRetry(
            f"Unknown native {tool_name} helper model. Choose a model from the "
            f"{normalized_provider} model catalog or omit model."
        ) from exc
    if require_structured_output and not info.supports_structured_output:
        raise ModelRetry(
            f"Model '{normalized_provider}:{resolved_model}' does not support structured output."
        )

    return ResolvedModel(
        provider=normalized_provider,
        model=resolved_model,
        settings=dict(info.default_settings),
        max_steps=DEFAULT_MAX_STEPS,
    )


def resolve_agent_model(agent) -> ResolvedModel:
    """Resolve the model for an agent, falling back to settings defaults.

    Precedence per field: the agent's own column, else the configured default.
    The agent's ``model_settings`` override the catalog defaults shallowly.
    """
    provider = agent.model_provider or settings.DEFAULT_MODEL_PROVIDER
    model = agent.model or settings.DEFAULT_MODEL

    # Azure is deployment-based: the deployment name is customer-defined and not
    # part of the Python catalog, so membership is not validated for it.
    default_settings = (
        {}
        if provider == PROVIDER_AZURE
        else dict(_require_active(provider, model).default_settings)
    )

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


def resolve_history_summary_model() -> ResolvedModel:
    """Resolve the fixed model used by out-of-band history compaction."""
    provider = settings.AGENT_HISTORY_SUMMARY_MODEL_PROVIDER
    model = settings.AGENT_HISTORY_SUMMARY_MODEL
    info = _require_active(provider, model)

    return ResolvedModel(
        provider=provider,
        model=model,
        settings=dict(info.default_settings),
        max_steps=DEFAULT_MAX_STEPS,
    )


def resolve_model_context_budget(resolved_model: ResolvedModel) -> ModelContextBudget:
    """Resolve calibrated context accounting for catalog and Azure deployment models."""
    if resolved_model.provider == PROVIDER_AZURE:
        return ModelContextBudget(
            context_window=settings.AZURE_OPENAI_CONTEXT_WINDOW,
            chars_per_token=settings.AZURE_OPENAI_CHARS_PER_TOKEN,
        )
    info = _require_active(resolved_model.provider, resolved_model.model)
    return ModelContextBudget(
        context_window=info.context_window,
        chars_per_token=info.chars_per_token,
    )
