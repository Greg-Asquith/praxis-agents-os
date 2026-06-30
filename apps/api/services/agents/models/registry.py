# apps/api/services/agents/models/registry.py

"""The Python-owned model catalog: single source of truth for known models.

Adding or swapping a model is a one-entry edit to ``_CATALOG``. This module has
no database and no per-workspace overrides by design — per-agent selection lives
on the Agent row, and the one utility use case (naming) is a settings constant.
The SPA will read this catalog through an API route in a later step.
"""

from services.agents.models.domain import (
    PROVIDER_ANTHROPIC,
    PROVIDER_GOOGLE,
    PROVIDER_OPENAI,
    ModelConfigurationError,
    ModelInfo,
)

_CATALOG: tuple[ModelInfo, ...] = (
    # OpenAI (GPT-5.x family; reasoning + vision across the line)
    ModelInfo(
        provider=PROVIDER_OPENAI,
        model="gpt-5.5",
        display_name="GPT-5.5",
        context_window=1_000_000,
        supports_thinking=True,
        supports_vision=True,
    ),
    ModelInfo(
        provider=PROVIDER_OPENAI,
        model="gpt-5.4",
        display_name="GPT-5.4",
        context_window=1_000_000,
        supports_thinking=True,
        supports_vision=True,
    ),
    ModelInfo(
        provider=PROVIDER_OPENAI,
        model="gpt-5.4-mini",
        display_name="GPT-5.4 mini",
        context_window=1_000_000,
        supports_thinking=True,
        supports_vision=True,
    ),
    ModelInfo(
        provider=PROVIDER_OPENAI,
        model="gpt-5.4-nano",
        display_name="GPT-5.4 nano",
        context_window=1_000_000,
        supports_vision=True,
    ),
    # Anthropic (model IDs are aliases — no date suffix)
    ModelInfo(
        provider=PROVIDER_ANTHROPIC,
        model="claude-fable-5",
        display_name="Claude Fable 5",
        context_window=1_000_000,
        supports_thinking=True,
        supports_vision=True,
    ),
    ModelInfo(
        provider=PROVIDER_ANTHROPIC,
        model="claude-opus-4-8",
        display_name="Claude Opus 4.8",
        context_window=1_000_000,
        supports_thinking=True,
        supports_vision=True,
    ),
    ModelInfo(
        provider=PROVIDER_ANTHROPIC,
        model="claude-opus-4-7",
        display_name="Claude Opus 4.7",
        context_window=800_000,
        supports_thinking=True,
        supports_vision=True,
    ),
    ModelInfo(
        provider=PROVIDER_ANTHROPIC,
        model="claude-opus-4-6",
        display_name="Claude Opus 4.6",
        context_window=800_000,
        supports_thinking=True,
        supports_vision=True,
    ),
    ModelInfo(
        provider=PROVIDER_ANTHROPIC,
        model="claude-sonnet-4-6",
        display_name="Claude Sonnet 4.6",
        context_window=1_000_000,
        supports_thinking=True,
        supports_vision=True,
    ),
    ModelInfo(
        provider=PROVIDER_ANTHROPIC,
        model="claude-haiku-4-5",
        display_name="Claude Haiku 4.5",
        context_window=200_000,
        supports_vision=True,
    ),
    # Google (Gemini Developer API or Vertex AI; selection is a settings concern)
    ModelInfo(
        provider=PROVIDER_GOOGLE,
        model="gemini-3.5-flash",
        display_name="Gemini 3.5 Flash",
        context_window=1_000_000,
        supports_thinking=True,
        supports_vision=True,
    ),
    ModelInfo(
        provider=PROVIDER_GOOGLE,
        model="gemini-3.1-pro",
        display_name="Gemini 3.1 Pro",
        context_window=1_000_000,
        supports_thinking=True,
        supports_vision=True,
    ),
    ModelInfo(
        provider=PROVIDER_GOOGLE,
        model="gemini-3.1-flash-lite",
        display_name="Gemini 3.1 Flash-Lite",
        context_window=1_000_000,
        supports_vision=True,
    ),
)

_INDEX: dict[tuple[str, str], ModelInfo] = {
    (info.provider, info.model): info for info in _CATALOG
}


def find_model(provider: str, model: str) -> ModelInfo | None:
    """Return the catalog entry, or None if not known."""
    return _INDEX.get((provider, model))


def get_model(provider: str, model: str) -> ModelInfo:
    """Return the catalog entry or raise if the model is not known."""
    info = _INDEX.get((provider, model))
    if info is None:
        raise ModelConfigurationError(
            f"Unknown model '{provider}:{model}'. Not present in the model catalog.",
            details={"provider": provider, "model": model},
        )
    return info


def is_known(provider: str, model: str) -> bool:
    """True if the provider/model pair exists in the catalog."""
    return (provider, model) in _INDEX


def qualified_id(provider: str, model: str) -> str:
    """Provider-qualified id for a known model, validating membership first."""
    return get_model(provider, model).qualified_id


def list_models(*, include_deprecated: bool = False) -> list[ModelInfo]:
    """All catalog entries, deprecated ones excluded unless requested."""
    return [m for m in _CATALOG if include_deprecated or not m.deprecated]
