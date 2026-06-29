# apps/api/core/auth/oauth_providers/google.py

"""
Google OAuth provider implementation.

Provides:
- OAuth2 authorization flow
- Token exchange and refresh
- User info retrieval
- Token revocation
"""

import logging
from typing import Any
from urllib.parse import urlencode

from core.auth.oauth_providers.retrying import OAuthProviderWithRetry
from core.settings import settings

logger = logging.getLogger(__name__)


class GoogleOAuthProvider(OAuthProviderWithRetry):
    def __init__(self):
        super().__init__(provider_name="google", provider_display_name="Google")
        self.client_id = settings.GOOGLE_OAUTH_CLIENT_ID
        self.client_secret = settings.GOOGLE_OAUTH_CLIENT_SECRET.get_secret_value()
        self.auth_url = "https://accounts.google.com/o/oauth2/v2/auth"
        self.token_url = "https://oauth2.googleapis.com/token"
        self.user_info_url = "https://www.googleapis.com/oauth2/v2/userinfo"
        self.revoke_url = "https://oauth2.googleapis.com/revoke"

    async def get_authorization_url(self, state: str, redirect_uri: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{self.auth_url}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        response = await self._make_request(
            method="POST",
            url=self.token_url,
            endpoint_name="token_exchange",
            data={
                "code": code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        return self._parse_token_payload(response, "token_exchange")

    async def get_user_info(self, access_token: str) -> dict[str, Any]:
        response = await self._make_request(
            method="GET",
            url=self.user_info_url,
            endpoint_name="user_info",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        data = response.json()

        # Drop the email unless Google reports it verified; linking on an unverified address is an account-takeover vector.
        if not (data.get("verified_email") or data.get("email_verified")):
            data["email"] = None
        return data

    async def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        response = await self._make_request(
            method="POST",
            url=self.token_url,
            endpoint_name="token_refresh",
            data={
                "refresh_token": refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
            },
        )
        return self._parse_token_payload(response, "token_refresh")

    async def revoke_token(self, token: str) -> bool:
        try:
            await self._make_request(
                method="POST",
                url=self.revoke_url,
                endpoint_name="token_revoke",
                params={"token": token},
            )
            return True
        except Exception as e:
            logger.warning("Failed to revoke %s OAuth token: %s", self.provider_display_name, e)
            return False
