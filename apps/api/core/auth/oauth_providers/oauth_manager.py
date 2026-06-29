# apps/api/core/auth/oauth_providers/oauth_manager.py

"""
OAuth provider manager for handling authentication with external services.

Provides:
- Base class for OAuth providers
"""

from abc import ABC, abstractmethod
from typing import Any


class OAuthProvider(ABC):
    """Base class for OAuth providers"""

    @abstractmethod
    async def get_authorization_url(self, state: str, redirect_uri: str) -> str:
        """Get the OAuth authorization URL"""

    @abstractmethod
    async def exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        """Exchange authorization code for tokens"""

    @abstractmethod
    async def get_user_info(self, access_token: str) -> dict[str, Any]:
        """Get user information from the provider"""

    @abstractmethod
    async def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh the access token"""

    @abstractmethod
    async def revoke_token(self, token: str) -> bool:
        """Revoke the access token (return False when the provider has no revocation endpoint)"""
