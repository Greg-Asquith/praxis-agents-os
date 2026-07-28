# apps/api/services/integrations/credentials/google_service_account.py

"""Mint short-lived Google OAuth tokens from reference-resolved service accounts."""

import json
from dataclasses import dataclass
from time import time
from typing import Any

import httpx2
import jwt

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationError,
    IntegrationValidationError,
)
from services.integrations.http import request_with_retries

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
JWT_BEARER_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"


@dataclass(frozen=True)
class GoogleServiceAccountCredentials:
    client_email: str
    private_key: str
    token_uri: str = GOOGLE_TOKEN_URL


def parse_google_service_account_json(
    value: str,
    *,
    provider_key: str,
) -> GoogleServiceAccountCredentials:
    """Validate the minimum server-to-server credential fields without leaking values."""
    try:
        payload = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise IntegrationValidationError(
            "Service-account credential must be valid JSON",
            provider_key=provider_key,
            operation="validate_service_account",
        ) from exc
    if not isinstance(payload, dict):
        raise IntegrationValidationError(
            "Service-account credential must be a JSON object",
            provider_key=provider_key,
            operation="validate_service_account",
        )
    client_email = str(payload.get("client_email", "")).strip()
    private_key = str(payload.get("private_key", "")).strip()
    token_uri = str(payload.get("token_uri", GOOGLE_TOKEN_URL)).strip()
    if (
        payload.get("type") != "service_account"
        or not client_email
        or not private_key
        or token_uri != GOOGLE_TOKEN_URL
    ):
        raise IntegrationValidationError(
            "Service-account credential is missing required fields",
            provider_key=provider_key,
            operation="validate_service_account",
        )
    return GoogleServiceAccountCredentials(
        client_email=client_email,
        private_key=private_key,
        token_uri=token_uri,
    )


class GoogleServiceAccountTokenProvider:
    """Cache only the short-lived access token for one resolved credential."""

    def __init__(
        self,
        credentials: GoogleServiceAccountCredentials,
        *,
        provider_key: str,
        scope: str,
        client: httpx2.AsyncClient | None = None,
    ) -> None:
        self.credentials = credentials
        self.provider_key = provider_key
        self.scope = scope
        self._client = client
        self._access_token: str | None = None
        self._expires_at = 0.0

    async def access_token(self, force: bool = False) -> str:
        now = time()
        if not force and self._access_token and now < self._expires_at - 60:
            return self._access_token
        issued_at = int(now)
        claims = {
            "iss": self.credentials.client_email,
            "sub": self.credentials.client_email,
            "scope": self.scope,
            "aud": self.credentials.token_uri,
            "iat": issued_at,
            "exp": issued_at + 3600,
        }
        try:
            assertion = jwt.encode(claims, self.credentials.private_key, algorithm="RS256")
        except Exception as exc:
            raise IntegrationValidationError(
                "Service-account private key is invalid",
                provider_key=self.provider_key,
                operation="mint_service_account_token",
            ) from exc
        try:
            response = await request_with_retries(
                "POST",
                self.credentials.token_uri,
                operation="mint_service_account_token",
                provider_key=self.provider_key,
                client=self._client,
                data={"grant_type": JWT_BEARER_GRANT, "assertion": assertion},
            )
        except IntegrationError as exc:
            # The retained request would contain the signed assertion.
            exc.original_error = None
            raise
        payload: Any
        try:
            payload = response.json()
        except ValueError as exc:
            raise IntegrationAuthError(
                "Google token exchange returned an invalid response",
                provider_key=self.provider_key,
                operation="mint_service_account_token",
            ) from exc
        token = str(payload.get("access_token", "")).strip() if isinstance(payload, dict) else ""
        if not token:
            raise IntegrationAuthError(
                "Google token exchange returned no access token",
                provider_key=self.provider_key,
                operation="mint_service_account_token",
            )
        expires_in = payload.get("expires_in", 3600)
        try:
            lifetime = max(60, int(expires_in))
        except (TypeError, ValueError):
            lifetime = 3600
        self._access_token = token
        self._expires_at = now + lifetime
        return token
