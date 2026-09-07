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
    PROVIDER_XAI,
    ModelConfigurationError,
    ModelInfo,
)

_CATALOG: tuple[ModelInfo, ...] = (
    # OpenAI (GPT-5.x family; reasoning + vision across the line)
    ModelInfo(
        provider=PROVIDER_OPENAI,
        model="gpt-5.6-sol",
        display_name="GPT-5.6 Sol",
        context_window=1_050_000,
        model_type="max",
        chars_per_token=4.0,
        supports_thinking=True,
        supports_vision=True,
    ),
    ModelInfo(
        provider=PROVIDER_OPENAI,
        model="gpt-5.6-terra",
        display_name="GPT-5.6 Terra",
        context_window=1_050_000,
        model_type="powerful",
        chars_per_token=4.0,
        supports_thinking=True,
        supports_vision=True,
    ),
    ModelInfo(
        provider=PROVIDER_OPENAI,
        model="gpt-5.6-luna",
        display_name="GPT-5.6 Luna",
        context_window=1_050_000,
        model_type="standard",
        chars_per_token=4.0,
        supports_thinking=True,
        supports_vision=True,
    ),
    ModelInfo(
        provider=PROVIDER_OPENAI,
        model="gpt-5.5",
        display_name="GPT-5.5",
        context_window=1_050_000,
        model_type="max",
        chars_per_token=4.0,
        supports_thinking=True,
        supports_vision=True,
    ),
    ModelInfo(
        provider=PROVIDER_OPENAI,
        model="gpt-5.4",
        display_name="GPT-5.4",
        context_window=1_050_000,
        model_type="powerful",
        chars_per_token=4.0,
        supports_thinking=True,
        supports_vision=True,
    ),
    ModelInfo(
        provider=PROVIDER_OPENAI,
        model="gpt-5.4-mini",
        display_name="GPT-5.4 Mini",
        context_window=400_000,
        model_type="standard",
        chars_per_token=4.0,
        supports_thinking=True,
        supports_vision=True,
    ),
    ModelInfo(
        provider=PROVIDER_OPENAI,
        model="gpt-5.4-nano",
        display_name="GPT-5.4 Nano",
        context_window=400_000,
        model_type="light",
        chars_per_token=4.0,
        supports_vision=True,
    ),
    # Anthropic (Vertex IDs follow the Model Garden cards, checked 2026-09-04).
    # Model Garden: Claude Fable 5.1 on Google Cloud.
    ModelInfo(
        provider=PROVIDER_ANTHROPIC,
        model="claude-fable-5-1",
        vertex_model="claude-fable-5-1",
        display_name="Claude Fable 5.1",
        context_window=1_000_000,
        model_type="max",
        chars_per_token=4.0,
        supports_thinking=True,
        supports_vision=True,
    ),
    # Model Garden: Claude Fable 5 on Google Cloud.
    ModelInfo(
        provider=PROVIDER_ANTHROPIC,
        model="claude-fable-5",
        vertex_model="claude-fable-5",
        display_name="Claude Fable 5",
        context_window=1_000_000,
        model_type="max",
        chars_per_token=4.0,
        supports_thinking=True,
        supports_vision=True,
    ),
    # Model Garden: Claude Opus 4.8 on Google Cloud.
    ModelInfo(
        provider=PROVIDER_ANTHROPIC,
        model="claude-opus-4-8",
        vertex_model="claude-opus-4-8",
        display_name="Claude Opus 4.8",
        context_window=1_000_000,
        model_type="powerful",
        chars_per_token=4.0,
        supports_thinking=True,
        supports_vision=True,
    ),
    # Model Garden: Claude Opus 4.7 on Google Cloud.
    ModelInfo(
        provider=PROVIDER_ANTHROPIC,
        model="claude-opus-4-7",
        vertex_model="claude-opus-4-7",
        display_name="Claude Opus 4.7",
        context_window=1_000_000,
        model_type="powerful",
        chars_per_token=4.0,
        supports_thinking=True,
        supports_vision=True,
    ),
    # Model Garden: Claude Opus 4.6 on Google Cloud.
    ModelInfo(
        provider=PROVIDER_ANTHROPIC,
        model="claude-opus-4-6",
        vertex_model="claude-opus-4-6",
        display_name="Claude Opus 4.6",
        context_window=1_000_000,
        model_type="powerful",
        chars_per_token=4.0,
        supports_thinking=True,
        supports_vision=True,
    ),
    # Model Garden: Claude Sonnet 5 on Google Cloud.
    ModelInfo(
        provider=PROVIDER_ANTHROPIC,
        model="claude-sonnet-5",
        vertex_model="claude-sonnet-5",
        display_name="Claude Sonnet 5",
        context_window=1_000_000,
        model_type="standard",
        chars_per_token=4.0,
        supports_thinking=True,
        supports_vision=True,
    ),
    # Model Garden: Claude Sonnet 4.6 on Google Cloud.
    ModelInfo(
        provider=PROVIDER_ANTHROPIC,
        model="claude-sonnet-4-6",
        vertex_model="claude-sonnet-4-6",
        display_name="Claude Sonnet 4.6",
        context_window=1_000_000,
        model_type="standard",
        chars_per_token=4.0,
        supports_thinking=True,
        supports_vision=True,
    ),
    # Model Garden: Claude Haiku 4.5 on Google Cloud.
    ModelInfo(
        provider=PROVIDER_ANTHROPIC,
        model="claude-haiku-4-5",
        vertex_model="claude-haiku-4-5",
        display_name="Claude Haiku 4.5",
        context_window=200_000,
        model_type="light",
        chars_per_token=4.0,
        supports_vision=True,
    ),
    # Google (Gemini Developer API or Vertex AI; selection is a settings concern)
    ModelInfo(
        provider=PROVIDER_GOOGLE,
        model="gemini-3.8-flash",
        display_name="Gemini 3.8 Flash",
        context_window=1_048_576,
        model_type="standard",
        chars_per_token=4.0,
        supports_thinking=True,
        supports_vision=True,
        vertex_model="gemini-3.8-flash",
    ),
    ModelInfo(
        provider=PROVIDER_GOOGLE,
        model="gemini-3.7-flash",
        display_name="Gemini 3.7 Flash",
        context_window=1_048_576,
        model_type="standard",
        chars_per_token=4.0,
        supports_thinking=True,
        supports_vision=True,
        vertex_model="gemini-3.7-flash",
    ),
    ModelInfo(
        provider=PROVIDER_GOOGLE,
        model="gemini-3.6-flash",
        display_name="Gemini 3.6 Flash",
        context_window=1_048_576,
        model_type="standard",
        chars_per_token=4.0,
        supports_thinking=True,
        supports_vision=True,
        vertex_model="gemini-3.6-flash",
    ),
    ModelInfo(
        provider=PROVIDER_GOOGLE,
        model="gemini-3.5-flash",
        display_name="Gemini 3.5 Flash",
        context_window=1_048_576,
        model_type="standard",
        chars_per_token=4.0,
        supports_thinking=True,
        supports_vision=True,
        vertex_model="gemini-3.5-flash",
    ),
    ModelInfo(
        provider=PROVIDER_GOOGLE,
        model="gemini-3.5-flash-lite",
        display_name="Gemini 3.5 Flash-Lite",
        context_window=1_048_576,
        model_type="light",
        chars_per_token=4.0,
        supports_thinking=True,
        supports_vision=True,
        vertex_model="gemini-3.5-flash-lite",
    ),
    ModelInfo(
        provider=PROVIDER_GOOGLE,
        model="gemini-3.1-pro",
        display_name="Gemini 3.1 Pro",
        context_window=1_048_576,
        model_type="powerful",
        chars_per_token=4.0,
        supports_thinking=True,
        supports_vision=True,
        vertex_model="gemini-3.1-pro",
    ),
    ModelInfo(
        provider=PROVIDER_GOOGLE,
        model="gemini-3.1-flash-lite",
        display_name="Gemini 3.1 Flash Lite",
        context_window=1_048_576,
        model_type="light",
        chars_per_token=4.0,
        supports_vision=True,
        vertex_model="gemini-3.1-flash-lite",
    ),
    # Model Garden Grok 4.20 cards; streaming, tools, JSON, and vision probed 2026-09-05.
    # https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/partner-models/grok/grok-4-20
    ModelInfo(
        provider=PROVIDER_XAI,
        model="grok-4-20-reasoning",
        display_name="Grok 4.20 (Reasoning)",
        context_window=2_000_000,
        model_type="powerful",
        supports_tools=True,
        supports_thinking=True,
        supports_vision=True,
        supports_structured_output=True,
        vertex_model="xai/grok-4.20-reasoning",
    ),
    ModelInfo(
        provider=PROVIDER_XAI,
        model="grok-4-20-non-reasoning",
        display_name="Grok 4.20 (Non-reasoning)",
        context_window=2_000_000,
        model_type="standard",
        supports_tools=True,
        supports_thinking=False,
        supports_vision=True,
        supports_structured_output=True,
        vertex_model="xai/grok-4.20-non-reasoning",
    ),
)

_INDEX: dict[tuple[str, str], ModelInfo] = {(info.provider, info.model): info for info in _CATALOG}


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
