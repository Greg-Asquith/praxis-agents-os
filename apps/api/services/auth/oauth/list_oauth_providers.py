# apps/api/services/auth/list_oauth_providers.py

"""List configured OAuth providers."""

from core.auth.oauth_providers.oauth_registry import oauth_registry
from services.auth.schemas import AuthProvider, AuthProvidersResponse


def list_oauth_providers() -> AuthProvidersResponse:
    return AuthProvidersResponse(
        providers=[
            AuthProvider(name=provider.name, display_name=provider.display_name, icon=provider.icon)
            for provider in oauth_registry.get_provider_info()
        ]
    )
