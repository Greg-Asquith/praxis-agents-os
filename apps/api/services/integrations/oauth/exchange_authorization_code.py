# apps/api/services/integrations/oauth/exchange_authorization_code.py

"""Exchange, refresh, and revoke provider OAuth tokens."""

from base64 import b64encode
from typing import Any

import httpx2

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationError,
    IntegrationFailureDisposition,
)
from core.settings import settings
from services.integrations.http import IntegrationRequestPolicy, request_with_retries
from services.integrations.oauth.resolve_provider_config import resolve_provider_oauth_config
from services.integrations.oauth.utils import parse_oauth_json_object
from services.integrations.plugin import OAuthClientConfig


async def exchange_authorization_code(
    *, provider_key: str, code: str, code_verifier: str
) -> dict[str, Any]:
    oauth_config = resolve_provider_oauth_config(provider_key)
    body = {"code": code}
    _add_post_client_credentials(oauth_config, body)
    body["redirect_uri"] = settings.INTEGRATIONS_OAUTH_REDIRECT_URI
    body["grant_type"] = "authorization_code"
    if oauth_config.protocol.pkce == "s256":
        body["code_verifier"] = code_verifier
    response = await request_with_retries(
        "POST",
        oauth_config.token_url,
        operation="oauth_token_exchange",
        provider_key=provider_key,
        policy=IntegrationRequestPolicy.MUTATION,
        response_error_mapper=lambda response: _token_response_error(
            response,
            provider_key=provider_key,
            operation="oauth_token_exchange",
            oauth_config=oauth_config,
        ),
        **_request_kwargs(oauth_config, body),
    )
    return _parse_token_payload(
        parse_oauth_json_object(
            response,
            provider_key=provider_key,
            operation="oauth_token_exchange",
        ),
        provider_key,
        "oauth_token_exchange",
        oauth_config,
    )


async def refresh_authorization_token(*, provider_key: str, refresh_token: str) -> dict[str, Any]:
    oauth_config = resolve_provider_oauth_config(provider_key)
    body = {"refresh_token": refresh_token}
    _add_post_client_credentials(oauth_config, body)
    body["grant_type"] = "refresh_token"
    response = await request_with_retries(
        "POST",
        oauth_config.token_url,
        operation="oauth_token_refresh",
        provider_key=provider_key,
        policy=IntegrationRequestPolicy.MUTATION,
        response_error_mapper=lambda response: _token_response_error(
            response,
            provider_key=provider_key,
            operation="oauth_token_refresh",
            oauth_config=oauth_config,
        ),
        **_request_kwargs(oauth_config, body),
    )
    return _parse_token_payload(
        parse_oauth_json_object(
            response,
            provider_key=provider_key,
            operation="oauth_token_refresh",
        ),
        provider_key,
        "oauth_token_refresh",
        oauth_config,
    )


async def revoke_authorization_token(*, provider_key: str, token: str) -> None:
    oauth_config = resolve_provider_oauth_config(provider_key)
    await request_with_retries(
        "POST",
        oauth_config.revoke_url,
        operation="oauth_token_revoke",
        provider_key=provider_key,
        policy=IntegrationRequestPolicy.MUTATION,
        **_request_kwargs(oauth_config, {"token": token}),
    )


def _request_kwargs(
    oauth_config: OAuthClientConfig,
    body: dict[str, str],
) -> dict[str, object]:
    protocol = oauth_config.protocol
    request_body = dict(body)
    headers = dict(protocol.request_headers)
    if protocol.token_auth == "client_secret_basic":
        raw_credentials = (
            f"{oauth_config.client_id}:{oauth_config.client_secret.get_secret_value()}".encode()
        )
        headers["Authorization"] = f"Basic {b64encode(raw_credentials).decode('ascii')}"

    kwargs: dict[str, object] = {}
    if headers:
        kwargs["headers"] = headers
    kwargs["data" if protocol.token_encoding == "form" else "json"] = request_body
    return kwargs


def _add_post_client_credentials(
    oauth_config: OAuthClientConfig,
    body: dict[str, str],
) -> None:
    if oauth_config.protocol.token_auth == "client_secret_post":
        body["client_id"] = oauth_config.client_id
        body["client_secret"] = oauth_config.client_secret.get_secret_value()


def _parse_token_payload(
    payload: Any,
    provider_key: str,
    operation: str,
    oauth_config: OAuthClientConfig,
) -> dict[str, Any]:
    rejection = _token_payload_error(
        payload,
        provider_key=provider_key,
        operation=operation,
        oauth_config=oauth_config,
    )
    if rejection is not None:
        raise rejection
    if not isinstance(payload.get("access_token"), str) or not payload["access_token"]:
        raise IntegrationAuthError(
            "OAuth token response did not include an access token",
            provider_key=provider_key,
            operation=operation,
        )
    return payload


def _token_response_error(
    response: httpx2.Response,
    *,
    provider_key: str,
    operation: str,
    oauth_config: OAuthClientConfig,
) -> IntegrationError | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    classifier = oauth_config.protocol.classify_token_error
    if not isinstance(payload, dict) or not payload.get("error") or classifier is None:
        return None
    error_code = classifier(payload)
    if error_code is None:
        return None
    return _oauth_token_error(
        provider_key=provider_key,
        operation=operation,
        error_code=error_code,
    )


def _token_payload_error(
    payload: Any,
    *,
    provider_key: str,
    operation: str,
    oauth_config: OAuthClientConfig,
) -> IntegrationAuthError | None:
    if isinstance(payload, dict) and not payload.get("error"):
        return None
    error_code = (
        oauth_config.protocol.classify_token_error(payload)
        if isinstance(payload, dict) and oauth_config.protocol.classify_token_error is not None
        else None
    )
    return _oauth_token_error(
        provider_key=provider_key,
        operation=operation,
        error_code=error_code,
    )


def _oauth_token_error(
    *,
    provider_key: str,
    operation: str,
    error_code: str | None,
) -> IntegrationAuthError:
    return IntegrationAuthError(
        "OAuth token response was rejected",
        provider_key=provider_key,
        operation=operation,
        error_code=error_code,
        failure_disposition=IntegrationFailureDisposition.REJECTED,
    )
