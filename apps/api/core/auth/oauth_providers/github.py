# apps/api/core/auth/oauth_providers/github.py

"""
GitHub OAuth provider implementation.

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


class GitHubOAuthProvider(OAuthProviderWithRetry):
    def __init__(self):
        super().__init__(provider_name="github", provider_display_name="GitHub")
        self.client_id = settings.GITHUB_OAUTH_CLIENT_ID
        self.client_secret = settings.GITHUB_OAUTH_CLIENT_SECRET.get_secret_value()
        self.auth_url = "https://github.com/login/oauth/authorize"
        self.token_url = "https://github.com/login/oauth/access_token"
        self.user_info_url = "https://api.github.com/user"
        self.user_emails_url = "https://api.github.com/user/emails"

    async def get_authorization_url(self, state: str, redirect_uri: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": "user:email",
            "state": state,
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
            },
            headers={"Accept": "application/json"},
        )
        return self._parse_token_payload(response, "token_exchange")

    async def get_user_info(self, access_token: str) -> dict[str, Any]:
        # Get user info
        user_response = await self._make_request(
            method="GET",
            url=self.user_info_url,
            endpoint_name="user_info",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        user_data = user_response.json()

        # Get primary email
        emails_response = await self._make_request(
            method="GET",
            url=self.user_emails_url,
            endpoint_name="user_emails",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        emails = emails_response.json()

        verified = [e for e in emails if e.get("verified", False) and e.get("email")]
        primary_email = next(
            (e["email"] for e in verified if e.get("primary", False)),
            verified[0]["email"] if verified else None,
        )

        user_data["email"] = primary_email
        return user_data

    async def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        # GitHub access tokens don't expire
        _ = refresh_token  # Unused but required by interface
        raise NotImplementedError("GitHub access tokens don't expire")

    async def revoke_token(self, token: str) -> bool:
        """Revoke GitHub access token"""
        try:
            response = await self._make_request(
                method="DELETE",
                url=f"https://api.github.com/applications/{self.client_id}/token",
                endpoint_name="token_revoke",
                json={"access_token": token},
                auth=(self.client_id, self.client_secret),
            )
            return response.status_code == 204
        except Exception as e:
            logger.warning("Failed to revoke %s OAuth token: %s", self.provider_display_name, e)
            return False
