# apps/api/services/agents/models/utils.py

"""Service-specific helpers for model resolution and construction.

``provider_api_key`` is the single seam through which provider credentials are
resolved. Today it reads Pydantic ``SecretStr`` settings (env/.local-loaded),
matching how the rest of the app sources secrets. When SECRET_PROVIDER's
secret-manager branches are wired, swap the body here without touching callers.
"""

from core.settings import settings
from services.agents.models.domain import (
    PROVIDER_ANTHROPIC,
    PROVIDER_AZURE,
    PROVIDER_GOOGLE,
    PROVIDER_OPENAI,
    ModelConfigurationError,
)

_PROVIDER_KEY_SETTING = {
    PROVIDER_ANTHROPIC: "ANTHROPIC_API_KEY",
    PROVIDER_OPENAI: "OPENAI_API_KEY",
    PROVIDER_GOOGLE: "GOOGLE_API_KEY",
    PROVIDER_AZURE: "AZURE_OPENAI_API_KEY",
}


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
        raise ModelConfigurationError(
            f"Missing credential for provider '{provider}': {setting_name} is not set.",
            details={"provider": provider, "setting": setting_name},
        )
    return secret.get_secret_value()
