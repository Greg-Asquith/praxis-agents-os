# apps/api/services/agents/models/list_model_catalog.py

"""List the model catalog entries usable with the current runtime settings."""

from pydantic import SecretStr

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
        provider for provider in _PROVIDER_ORDER if _provider_is_configured(provider)
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


def _provider_is_configured(provider: str) -> bool:
    if provider == PROVIDER_OPENAI:
        return _secret_has_text(settings.OPENAI_API_KEY)
    if provider == PROVIDER_ANTHROPIC:
        return _secret_has_text(settings.ANTHROPIC_API_KEY)
    if provider == PROVIDER_GOOGLE:
        if settings.GOOGLE_VERTEX_AI:
            return _has_text(settings.GOOGLE_VERTEX_PROJECT) or _has_text(settings.GCP_PROJECT_ID)
        return _secret_has_text(settings.GOOGLE_API_KEY)
    if provider == PROVIDER_AZURE:
        return _secret_has_text(settings.AZURE_OPENAI_API_KEY) and _has_text(
            settings.AZURE_OPENAI_ENDPOINT
        )
    return False


def _secret_has_text(secret: SecretStr | None) -> bool:
    return secret is not None and bool(secret.get_secret_value().strip())


def _has_text(value: str | None) -> bool:
    return bool((value or "").strip())
