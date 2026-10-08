# apps/api/services/agents/models/utils.py

"""Service-specific helpers for model resolution and construction.

``provider_api_key`` is the single seam through which provider credentials are
resolved. Today it reads Pydantic ``SecretStr`` settings (env/.local-loaded),
matching how the rest of the app sources secrets. When SECRET_PROVIDER's
secret-manager branches are wired, swap the body here without touching callers.
"""

from functools import lru_cache

import httpx2 as httpx
from pydantic_ai.models import DEFAULT_HTTP_TIMEOUT
from pydantic_ai.profiles import ModelProfile
from pydantic_ai.profiles.anthropic import anthropic_model_profile
from pydantic_ai.profiles.google import google_model_profile
from pydantic_ai.profiles.openai import openai_model_profile
from pydantic_ai.retries import wait_retry_after
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from core.settings import settings
from services.agents.models.domain import (
    PROVIDER_ANTHROPIC,
    PROVIDER_AZURE,
    PROVIDER_GOOGLE,
    PROVIDER_MISTRAL,
    PROVIDER_OPENAI,
    VERTEX_PARTNER_PROVIDERS,
    MissingModelCredentialError,
    ModelConfigurationError,
    ModelInfo,
    ProviderTransport,
    has_vertex_model_id,
)

_RETRYABLE_HTTP_STATUSES = frozenset({408, 409, 429, 500, 502, 503, 504, 529})
_PROVIDER_KEY_SETTING = {
    PROVIDER_ANTHROPIC: "ANTHROPIC_API_KEY",
    PROVIDER_OPENAI: "OPENAI_API_KEY",
    PROVIDER_GOOGLE: "GOOGLE_API_KEY",
    PROVIDER_AZURE: "AZURE_OPENAI_API_KEY",
}


ADAPTIVE_ONLY_ANTHROPIC_MODELS = frozenset({"claude-opus-5-5", "claude-sonnet-5-5"})


def provider_model_profile(provider: str, model: str) -> ModelProfile | None:
    """Supplies release profile settings missing from Pydantic AI 2.50."""
    if provider == PROVIDER_GOOGLE and model == "gemini-nano-banana-2.1":
        # Pydantic AI detects image models by an `image` substring in their IDs.
        return {
            **(google_model_profile("gemini-3.1-flash-image") or {}),
            "supports_json_schema_output": False,
            "supports_json_object_output": False,
            "thinking_always_enabled": True,
            "google_thinking_levels": frozenset({"MINIMAL", "MEDIUM", "HIGH"}),
        }
    if provider == PROVIDER_OPENAI and model == "gpt-6.1-sol":
        # 6.1 keeps GPT-6 Sol's Responses features but rejects the `none` effort.
        return {
            **openai_model_profile("gpt-6-sol"),
            "openai_supports_reasoning_effort_none": False,
            "thinking_always_enabled": True,
        }
    if provider == PROVIDER_ANTHROPIC and model in ADAPTIVE_ONLY_ANTHROPIC_MODELS:
        return {
            **(anthropic_model_profile(model) or {}),
            "thinking_always_enabled": True,
            "anthropic_supports_forced_tool_choice": False,
            "anthropic_binds_thinking_blocks": True,
            "default_structured_output_mode": "native",
        }
    if provider == PROVIDER_ANTHROPIC and model == "claude-haiku-5-5":
        # Haiku 5.5 rejects budget thinking and sampling settings but accepts disabled thinking.
        return {
            **(anthropic_model_profile(model) or {}),
            "supports_json_schema_output": True,
            "anthropic_supports_adaptive_thinking": True,
            "anthropic_supports_effort": True,
            "anthropic_supports_xhigh_effort": True,
            "anthropic_disallows_budget_thinking": True,
            "anthropic_disallows_sampling_settings": True,
            "anthropic_disallows_top_effort_when_thinking_disabled": True,
            "anthropic_binds_thinking_blocks": True,
        }
    return None


class _ProviderRetryTransport(httpx.AsyncBaseTransport):
    """Returns final HTTP responses intact so SDKs preserve provider errors."""

    def __init__(self, wrapped: httpx.AsyncBaseTransport | None = None) -> None:
        self.wrapped = wrapped or httpx.AsyncHTTPTransport()
        self.attempts = settings.LLM_HTTP_RETRY_MAX_ATTEMPTS
        self.wait = wait_retry_after(
            fallback_strategy=wait_exponential(
                multiplier=1, max=settings.LLM_HTTP_RETRY_MAX_WAIT_SECONDS
            ),
            max_wait=settings.LLM_HTTP_RETRY_TOTAL_WAIT_CAP_SECONDS,
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.attempts),
            wait=self.wait,
            retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
            reraise=True,
        ):
            with attempt:
                response = await self.wrapped.handle_async_request(request)
                response.request = request
                if (
                    response.status_code in _RETRYABLE_HTTP_STATUSES
                    and attempt.retry_state.attempt_number < self.attempts
                ):
                    await response.aclose()
                    response.raise_for_status()
                return response
        raise RuntimeError("Provider retry policy made no attempts.")  # pragma: no cover

    async def aclose(self) -> None:
        await self.wrapped.aclose()


def _build_retrying_http_client(
    wrapped: httpx.AsyncBaseTransport | None = None,
    *,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:
    transport = _ProviderRetryTransport(wrapped)
    return httpx.AsyncClient(
        auth=auth,
        transport=transport,
        timeout=httpx.Timeout(timeout=DEFAULT_HTTP_TIMEOUT, connect=5),
    )


@lru_cache(maxsize=1)
def retrying_http_client() -> httpx.AsyncClient:
    """Shared async client that retries transient provider failures."""
    return _build_retrying_http_client()


async def close_retrying_http_client() -> None:
    """Closes and forgets the shared client without creating one during shutdown."""
    if retrying_http_client.cache_info().currsize:
        client = retrying_http_client()
        retrying_http_client.cache_clear()
        if not client.is_closed:
            await client.aclose()


def provider_api_key(provider: str) -> str:
    """Resolve the API key for a provider, raising if it is not configured."""
    setting_name = _PROVIDER_KEY_SETTING.get(provider)
    if setting_name is None:
        raise ModelConfigurationError(
            f"No credential mapping for provider '{provider}'.",
            details={"provider": provider},
        )

    secret = getattr(settings, setting_name, None)
    if secret is None or not secret.get_secret_value().strip():
        raise MissingModelCredentialError(
            provider=provider,
            setting=setting_name,
        )
    return secret.get_secret_value()


def has_provider_api_key(provider: str) -> bool:
    """Return whether a provider has a non-empty configured API key."""
    setting_name = _PROVIDER_KEY_SETTING.get(provider)
    if setting_name is None:
        return False

    secret = getattr(settings, setting_name, None)
    return secret is not None and bool(secret.get_secret_value().strip())


def vertex_project() -> str | None:
    """Returns the configured Vertex AI project, including the deployment fallback."""
    for project in (settings.GOOGLE_VERTEX_PROJECT, settings.GCP_PROJECT_ID):
        normalized = (project or "").strip()
        if normalized:
            return normalized
    return None


def provider_transport(provider: str) -> ProviderTransport:
    """Returns the active transport for a model provider."""
    if provider == PROVIDER_GOOGLE and settings.GOOGLE_VERTEX_AI:
        return "google-cloud"
    if provider == PROVIDER_ANTHROPIC and settings.ANTHROPIC_VERTEX_AI:
        return "google-cloud"
    if provider in VERTEX_PARTNER_PROVIDERS:
        return "google-cloud"
    return "direct"


def is_provider_configured(provider: str) -> bool:
    """Return whether the provider has the runtime configuration needed to build a model."""
    if provider in VERTEX_PARTNER_PROVIDERS:
        return (
            settings.VERTEX_PARTNER_MODELS_ENABLED
            and vertex_project() is not None
            and any(alias.startswith(f"{provider}:") for alias in settings.VERTEX_PARTNER_MODELS)
        )
    if provider_transport(provider) == "google-cloud":
        return vertex_project() is not None
    if provider == PROVIDER_AZURE:
        return has_provider_api_key(provider) and bool(
            (settings.AZURE_OPENAI_ENDPOINT or "").strip()
        )
    return has_provider_api_key(provider)


def is_model_available(info: ModelInfo) -> bool:
    """Return whether this deployment can build the model on its active transport."""
    return is_provider_configured(info.provider) and (
        provider_transport(info.provider) == "direct"
        or (has_vertex_model_id(info.vertex_model) and is_vertex_model_enabled(info))
    )


def is_vertex_model_enabled(info: ModelInfo) -> bool:
    """Return whether the deployment's Vertex model list allows this Anthropic or partner model."""
    if info.provider in VERTEX_PARTNER_PROVIDERS:
        return info.qualified_id in settings.VERTEX_PARTNER_MODELS
    if info.provider == PROVIDER_ANTHROPIC and provider_transport(info.provider) == "google-cloud":
        return info.model in settings.ANTHROPIC_VERTEX_MODELS
    return True


def partner_location(info: ModelInfo) -> str:
    """Return a supported override or the model's default location."""
    location = settings.VERTEX_PARTNER_MODEL_LOCATIONS.get(
        info.qualified_id, info.vertex_default_location
    )
    if (
        info.partner_transport
        != ("mistral-publisher" if info.provider == PROVIDER_MISTRAL else "chat-completions")
        or not info.vertex_default_location
        or info.vertex_default_location not in info.vertex_supported_locations
        or not location
        or location not in info.vertex_supported_locations
    ):
        raise ModelConfigurationError(
            f"Model '{info.qualified_id}' has missing or unsupported Vertex routing metadata.",
            details={"model": info.qualified_id, "setting": "VERTEX_PARTNER_MODEL_LOCATIONS"},
        )
    return location
