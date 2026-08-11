# apps/api/services/agents/models/list_model_catalog.py

"""List the model catalog entries usable with the current runtime settings."""

from core.settings import settings
from services.agents.models.domain import (
    PROVIDER_ANTHROPIC,
    PROVIDER_AZURE,
    PROVIDER_GOOGLE,
    PROVIDER_OPENAI,
    ModelInfo,
)
from services.agents.models.registry import list_models
from services.agents.models.schemas import (
    ModelCatalogDefaults,
    ModelCatalogEntry,
    ModelCatalogProvider,
    ModelCatalogResponse,
)
from services.agents.models.utils import is_provider_configured

_PROVIDER_DISPLAY_NAMES = {
    PROVIDER_OPENAI: "OpenAI",
    PROVIDER_ANTHROPIC: "Anthropic",
    PROVIDER_GOOGLE: "Google",
    PROVIDER_AZURE: "Azure OpenAI",
}

_PROVIDER_ORDER = (
    PROVIDER_OPENAI,
    PROVIDER_ANTHROPIC,
    PROVIDER_GOOGLE,
    PROVIDER_AZURE,
)


def list_model_catalog() -> ModelCatalogResponse:
    """Return non-deprecated catalog models whose provider is configured."""
    configured_providers = {
        provider for provider in _PROVIDER_ORDER if is_provider_configured(provider)
    }
    available_models = [model for model in list_models() if model.provider in configured_providers]
    available_ids = {model.qualified_id for model in available_models}

    return ModelCatalogResponse(
        providers=[
            ModelCatalogProvider(
                provider=provider,
                display_name=_PROVIDER_DISPLAY_NAMES[provider],
                configured=provider in configured_providers,
                model_count=sum(1 for model in available_models if model.provider == provider),
            )
            for provider in _PROVIDER_ORDER
        ],
        models=[_catalog_entry(model) for model in available_models],
        defaults=ModelCatalogDefaults(
            agent_model=_default_if_available(
                settings.DEFAULT_MODEL_PROVIDER,
                settings.DEFAULT_MODEL,
                available_ids,
            ),
        ),
    )


def _catalog_entry(model: ModelInfo) -> ModelCatalogEntry:
    return ModelCatalogEntry(
        id=model.qualified_id,
        provider=model.provider,
        model=model.model,
        display_name=model.display_name,
        context_window=model.context_window,
        supports_tools=model.supports_tools,
        supports_thinking=model.supports_thinking,
        supports_vision=model.supports_vision,
        supports_structured_output=model.supports_structured_output,
        default_settings=dict(model.default_settings),
    )


def _default_if_available(provider: str, model: str, available_ids: set[str]) -> str | None:
    qualified_id = f"{provider}:{model}"
    return qualified_id if qualified_id in available_ids else None
