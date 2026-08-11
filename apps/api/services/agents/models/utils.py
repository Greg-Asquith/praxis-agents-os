# apps/api/services/agents/models/utils.py

"""Service-specific helpers for model resolution and construction.

``provider_api_key`` is the single seam through which provider credentials are
resolved. Today it reads Pydantic ``SecretStr`` settings (env/.local-loaded),
matching how the rest of the app sources secrets. When SECRET_PROVIDER's
secret-manager branches are wired, swap the body here without touching callers.
"""

from functools import lru_cache

# OpenAI, Anthropic, and Google provider SDKs currently enforce the original
# httpx AsyncClient type at runtime and reject httpx2 clients.
import httpx
from pydantic_ai.models import DEFAULT_HTTP_TIMEOUT
from pydantic_ai.retries import AsyncTenacityTransport, RetryConfig, wait_retry_after
from tenacity import stop_after_attempt, wait_exponential

from core.settings import settings
from services.agents.models.domain import (
    PROVIDER_ANTHROPIC,
    PROVIDER_AZURE,
    PROVIDER_GOOGLE,
    PROVIDER_OPENAI,
    MissingModelCredentialError,
    ModelConfigurationError,
)

_RETRYABLE_HTTP_STATUSES = frozenset({408, 409, 429, 500, 502, 503, 504, 529})
_PROVIDER_KEY_SETTING = {
    PROVIDER_ANTHROPIC: "ANTHROPIC_API_KEY",
    PROVIDER_OPENAI: "OPENAI_API_KEY",
    PROVIDER_GOOGLE: "GOOGLE_API_KEY",
    PROVIDER_AZURE: "AZURE_OPENAI_API_KEY",
}


def _raise_for_retryable_status(response: httpx.Response) -> None:
    """Raise only for transient statuses that should be retried."""
    if response.status_code in _RETRYABLE_HTTP_STATUSES:
        response.raise_for_status()


def _build_retrying_http_client(
    wrapped: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    transport = AsyncTenacityTransport(
        config=RetryConfig(
            stop=stop_after_attempt(settings.LLM_HTTP_RETRY_MAX_ATTEMPTS),
            wait=wait_retry_after(
                fallback_strategy=wait_exponential(
                    multiplier=1,
                    max=settings.LLM_HTTP_RETRY_MAX_WAIT_SECONDS,
                ),
                max_wait=settings.LLM_HTTP_RETRY_TOTAL_WAIT_CAP_SECONDS,
            ),
            reraise=True,
        ),
        wrapped=wrapped,
        validate_response=_raise_for_retryable_status,
    )
    return httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(timeout=DEFAULT_HTTP_TIMEOUT, connect=5),
    )


@lru_cache(maxsize=1)
def retrying_http_client() -> httpx.AsyncClient:
    """Shared async client that retries transient provider failures."""
    return _build_retrying_http_client()


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


def is_provider_configured(provider: str) -> bool:
    """Return whether the provider has the runtime configuration needed to build a model."""
    if provider == PROVIDER_GOOGLE and settings.GOOGLE_VERTEX_AI:
        project = settings.GOOGLE_VERTEX_PROJECT or settings.GCP_PROJECT_ID
        return bool((project or "").strip())
    if provider == PROVIDER_AZURE:
        return has_provider_api_key(provider) and bool(
            (settings.AZURE_OPENAI_ENDPOINT or "").strip()
        )
    return has_provider_api_key(provider)
