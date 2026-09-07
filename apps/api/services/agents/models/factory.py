# apps/api/services/agents/models/factory.py

"""Construct a Pydantic AI model instance from a resolved spec.

Credentials are injected explicitly (never relying on Pydantic AI's implicit
env-var pickup) via the ``provider_api_key`` seam. Google and Anthropic can route
through their direct APIs or Vertex AI depending on settings. Keeping construction
here means the runtime loop stays library-agnostic.
"""

from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.azure import AzureProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider

from core.settings import settings
from services.agents.models.domain import (
    PROVIDER_ANTHROPIC,
    PROVIDER_AZURE,
    PROVIDER_GOOGLE,
    PROVIDER_OPENAI,
    VERTEX_PARTNER_PROVIDERS,
    ModelConfigurationError,
    ResolvedModel,
)
from services.agents.models.utils import (
    provider_api_key,
    provider_transport,
    retrying_http_client,
    vertex_project,
)
from services.agents.models.vertex_clients import (
    get_anthropic_vertex_client,
    get_google_vertex_client,
)
from services.agents.models.vertex_openai_client import get_vertex_openai_client, partner_base_url


def build_model(spec: ResolvedModel) -> Model:
    """Build a ready-to-run Pydantic AI model for the resolved spec."""
    model_settings = _model_settings_for(spec)

    if spec.provider == PROVIDER_ANTHROPIC:
        if provider_transport(PROVIDER_ANTHROPIC) == "google-cloud":
            provider = AnthropicProvider(anthropic_client=get_anthropic_vertex_client())
        else:
            provider = AnthropicProvider(
                api_key=provider_api_key(PROVIDER_ANTHROPIC),
                http_client=retrying_http_client(),
            )
        return AnthropicModel(spec.transport_model, provider=provider, settings=model_settings)

    if spec.provider == PROVIDER_OPENAI:
        provider = OpenAIProvider(
            base_url=settings.OPENAI_BASE_URL,
            api_key=provider_api_key(PROVIDER_OPENAI),
            http_client=retrying_http_client(),
        )
        return OpenAIResponsesModel(
            spec.transport_model, provider=provider, settings=model_settings
        )

    if spec.provider == PROVIDER_GOOGLE:
        return GoogleModel(
            spec.transport_model, provider=_google_provider(), settings=model_settings
        )

    if spec.provider == PROVIDER_AZURE:
        return _build_azure_model(spec, model_settings)

    if spec.provider in VERTEX_PARTNER_PROVIDERS:
        return _build_partner_model(spec, model_settings)

    raise ModelConfigurationError(
        f"Unsupported model provider '{spec.provider}'.",
        details={"provider": spec.provider},
    )


def _google_provider() -> GoogleProvider:
    """Gemini Developer API by default; Vertex AI (ADC) when configured."""
    if not settings.GOOGLE_VERTEX_AI:
        return GoogleProvider(
            api_key=provider_api_key(PROVIDER_GOOGLE),
            http_client=retrying_http_client(),
        )

    return GoogleProvider(client=get_google_vertex_client())


def _model_settings_for(spec: ResolvedModel):
    model_settings = dict(spec.settings)
    if spec.provider == PROVIDER_ANTHROPIC and settings.AGENT_PROMPT_CACHE_ENABLED:
        model_settings = {
            "anthropic_cache": True,
            "anthropic_cache_instructions": True,
            "anthropic_cache_tool_definitions": True,
            **model_settings,
        }
    return model_settings or None


def _build_partner_model(spec: ResolvedModel, model_settings) -> Model:
    if not settings.VERTEX_PARTNER_MODELS_ENABLED:
        raise ModelConfigurationError(
            "Vertex partner models require VERTEX_PARTNER_MODELS_ENABLED=true.",
            details={"provider": spec.provider},
        )
    project = vertex_project()
    if not project:
        raise ModelConfigurationError(
            "Vertex AI requires a project (GOOGLE_VERTEX_PROJECT or GCP_PROJECT_ID).",
            details={"provider": spec.provider},
        )
    provider = OpenAIProvider(
        base_url=partner_base_url(project, settings.VERTEX_PARTNER_LOCATION),
        api_key="unused",
        http_client=get_vertex_openai_client(),
    )
    return OpenAIChatModel(spec.transport_model, provider=provider, settings=model_settings)


def _build_azure_model(spec: ResolvedModel, model_settings) -> Model:
    """Azure OpenAI is deployment-based: prefer the agent's azure_deployment."""
    endpoint = (settings.AZURE_OPENAI_ENDPOINT or "").strip()
    if not endpoint:
        raise ModelConfigurationError(
            "Azure OpenAI requires AZURE_OPENAI_ENDPOINT.",
            details={"provider": PROVIDER_AZURE},
        )

    provider = AzureProvider(
        azure_endpoint=endpoint,
        api_version=settings.AZURE_OPENAI_API_VERSION,
        api_key=provider_api_key(PROVIDER_AZURE),
        http_client=retrying_http_client(),
    )
    deployment = spec.azure_deployment or spec.transport_model
    return OpenAIChatModel(deployment, provider=provider, settings=model_settings)
