# apps/api/core/auth/oauth_providers/oauth_registry.py

"""
OAuth provider manager for handling authentication with external services.

Provides:
- Registry for managing OAuth providers
- Auto-registration of providers based on env vars
"""

import logging
from dataclasses import dataclass

from core.auth.oauth_providers.oauth_manager import OAuthProvider
from core.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class ProviderInfo:
    """OAuth provider information for frontend display"""

    name: str
    display_name: str
    icon: str


class OAuthProviderRegistry:
    """Registry for OAuth providers"""

    def __init__(self):
        self._providers: dict[str, type[OAuthProvider]] = {}
        self._provider_info: dict[str, ProviderInfo] = {}

    def register_provider(self, name: str, provider_class: type, display_name: str, icon: str):
        """Register an OAuth provider with display information"""
        if not issubclass(provider_class, OAuthProvider):
            raise TypeError(f"Provider {provider_class} must inherit from OAuthProvider")
        self._providers[name] = provider_class
        self._provider_info[name] = ProviderInfo(name=name, display_name=display_name, icon=icon)

    def get_provider(self, name: str) -> OAuthProvider | None:
        """Get an OAuth provider instance"""
        if name not in self._providers:
            return None
        return self._providers[name]()

    def get_available_providers(self) -> list[str]:
        """Get list of available provider names"""
        return list(self._providers.keys())

    def get_provider_info(self) -> list[ProviderInfo]:
        """Get list of provider information for frontend display"""
        return list(self._provider_info.values())


# Global provider registry instance
oauth_registry = OAuthProviderRegistry()


# Auto-register providers
def _auto_register_providers():
    """Auto-register OAuth providers with display information"""

    try:
        if settings.GOOGLE_OAUTH_ENABLED:
            from core.auth.oauth_providers.google import GoogleOAuthProvider

            oauth_registry.register_provider("google", GoogleOAuthProvider, "Google", "google")
    except Exception:
        logger.exception("Failed to register %s provider", "google")

    try:
        if settings.GITHUB_OAUTH_ENABLED:
            from core.auth.oauth_providers.github import GitHubOAuthProvider

            oauth_registry.register_provider("github", GitHubOAuthProvider, "GitHub", "github")
    except Exception:
        logger.exception("Failed to register %s provider", "github")

    try:
        if settings.MICROSOFT_OAUTH_ENABLED:
            from core.auth.oauth_providers.microsoft import MicrosoftOAuthProvider

            oauth_registry.register_provider(
                "microsoft", MicrosoftOAuthProvider, "Microsoft", "microsoft"
            )
    except Exception:
        logger.exception("Failed to register %s provider", "microsoft")


_auto_register_providers()
