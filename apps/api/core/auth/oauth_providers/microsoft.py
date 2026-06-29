# apps/api/core/auth/oauth_providers/microsoft.py

"""
Microsoft OAuth provider implementation.

Provides:
- OAuth2 authorization flow with Microsoft Identity Platform
- Token exchange and refresh
- User info retrieval from Microsoft Graph
- Token revocation
"""

import base64
import logging
from typing import Any
from urllib.parse import urlencode

from core.auth.oauth_providers.retrying import OAuthProviderWithRetry
from core.settings import settings

logger = logging.getLogger(__name__)


class MicrosoftOAuthProvider(OAuthProviderWithRetry):
    def __init__(self):
        super().__init__(provider_name="microsoft", provider_display_name="Microsoft")
        self.client_id = settings.MICROSOFT_OAUTH_CLIENT_ID
        self.client_secret = settings.MICROSOFT_OAUTH_CLIENT_SECRET.get_secret_value()
        self.tenant = "common"  # Allow both personal and work/school accounts
        self.auth_url = f"https://login.microsoftonline.com/{self.tenant}/oauth2/v2.0/authorize"
        self.token_url = f"https://login.microsoftonline.com/{self.tenant}/oauth2/v2.0/token"
        self.user_info_url = "https://graph.microsoft.com/v1.0/me"
        self.revoke_url = f"https://login.microsoftonline.com/{self.tenant}/oauth2/v2.0/logout"

    async def get_authorization_url(self, state: str, redirect_uri: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            # offline_access ensures refresh token issuance
            "scope": "openid email profile offline_access User.Read",
            "state": state,
            "response_mode": "query",
            "prompt": "select_account",
        }
        return f"{self.auth_url}?{urlencode(params)}"

    async def exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        response = await self._make_request(
            method="POST",
            url=self.token_url,
            endpoint_name="token_exchange",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "code": code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                # Including scope helps ensure refresh token issuance with v2.0 endpoint
                "scope": "openid email profile offline_access User.Read",
            },
        )
        return self._parse_token_payload(response, "token_exchange")

    async def get_user_info(self, access_token: str) -> dict[str, Any]:
        # Basic profile from Graph
        response = await self._make_request(
            method="GET",
            url=self.user_info_url,
            endpoint_name="user_info",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        data = response.json()

        # Try to fetch a small profile photo; if unavailable, ignore
        try:
            photo_resp = await self._make_request(
                method="GET",
                url="https://graph.microsoft.com/v1.0/me/photos/48x48/$value",
                endpoint_name="user_photo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            # Convert binary to data URL (JPEG is typical)
            if photo_resp.content:
                b64 = base64.b64encode(photo_resp.content).decode("ascii")
                data["picture"] = f"data:image/jpeg;base64,{b64}"
        except Exception:
            # Non-fatal; many accounts may have no photo
            logger.debug("Failed to fetch Microsoft profile photo", exc_info=True)

        return data

    async def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        response = await self._make_request(
            method="POST",
            url=self.token_url,
            endpoint_name="token_refresh",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "refresh_token": refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
            },
        )
        return self._parse_token_payload(response, "token_refresh")

    async def revoke_token(self, token: str) -> bool:
        """
        Microsoft does not expose a server-side token revocation endpoint.

        The logout URL is a browser-redirect flow and cannot revoke tokens
        server-to-server. This method is a no-op and always returns False to
        signal that revocation is not supported.
        """
        logger.debug(
            "%s does not support server-side token revocation; skipping",
            self.provider_display_name,
        )
        return False
