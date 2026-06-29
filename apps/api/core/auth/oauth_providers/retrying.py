# apps/api/core/auth/oauth_providers/retrying.py

"""Shared retry/error handling for OAuth provider HTTP calls."""

import asyncio
import logging
from typing import Any

import httpx2

from core.auth.oauth_providers.oauth_manager import OAuthProvider
from core.exceptions.oauth import OAuthAuthenticationError, OAuthNetworkError
from core.settings import settings

logger = logging.getLogger(__name__)


class OAuthProviderWithRetry(OAuthProvider):
    """Base OAuth provider with common HTTP retry behavior."""

    def __init__(self, *, provider_name: str, provider_display_name: str) -> None:
        self.provider_name = provider_name
        self.provider_display_name = provider_display_name
        self.timeout = settings.OAUTH_REQUEST_TIMEOUT
        self.max_retries = settings.OAUTH_MAX_RETRIES
        self.backoff_factor = settings.OAUTH_BACKOFF_FACTOR

    def _parse_token_payload(
        self, response: "httpx2.Response", endpoint_name: str
    ) -> dict[str, Any]:
        """Parse a token-endpoint JSON body, raising on 200-with-error responses.

        Providers (notably GitHub's token endpoint) can return HTTP 200 with an
        ``{"error": ...}`` body or omit ``access_token``; treat both as failures.
        """
        data = response.json()
        if not isinstance(data, dict) or data.get("error") or not data.get("access_token"):
            logger.error(
                "%s OAuth %s returned an invalid token payload (error=%s)",
                self.provider_display_name,
                endpoint_name,
                data.get("error") if isinstance(data, dict) else "non-object",
            )
            raise OAuthAuthenticationError(
                message=f"{self.provider_display_name} OAuth authentication failed on {endpoint_name}",
                provider=self.provider_name,
                endpoint=endpoint_name,
            )
        return data

    async def _make_request(
        self,
        method: str,
        url: str,
        endpoint_name: str,
        **kwargs: Any,
    ) -> httpx2.Response:
        """Make an OAuth provider HTTP request with retries and mapped errors."""
        kwargs.setdefault("timeout", self.timeout)
        last_exception: OAuthNetworkError | None = None

        async with httpx2.AsyncClient() as client:
            for attempt in range(self.max_retries + 1):
                try:
                    response = await client.request(method, url, **kwargs)
                    response.raise_for_status()
                    return response
                except httpx2.HTTPStatusError as exc:
                    status_code = exc.response.status_code
                    if 400 <= status_code < 500:
                        # Provider bodies may reflect codes/tokens; keep them in the server log only and raise a generic message.
                        logger.exception(
                            "%s OAuth %s client error: %s - %s",
                            self.provider_display_name,
                            endpoint_name,
                            status_code,
                            exc.response.text,
                        )
                        raise OAuthAuthenticationError(
                            message=(
                                f"{self.provider_display_name} OAuth authentication failed"
                                f" on {endpoint_name}"
                            ),
                            provider=self.provider_name,
                            endpoint=endpoint_name,
                        ) from exc

                    logger.warning(
                        "%s OAuth %s attempt %s failed: %s",
                        self.provider_display_name,
                        endpoint_name,
                        attempt + 1,
                        status_code,
                    )
                    last_exception = OAuthNetworkError(
                        message=f"{self.provider_display_name} OAuth server error: {status_code}",
                        provider=self.provider_name,
                        endpoint=endpoint_name,
                    )
                except (TimeoutError, httpx2.RequestError) as exc:
                    logger.warning(
                        "%s OAuth %s network error on attempt %s: %s",
                        self.provider_display_name,
                        endpoint_name,
                        attempt + 1,
                        exc,
                    )
                    last_exception = OAuthNetworkError(
                        message=f"{self.provider_display_name} OAuth network error: {exc}",
                        provider=self.provider_name,
                        endpoint=endpoint_name,
                    )

                if attempt < self.max_retries:
                    wait_time = self.backoff_factor * (2**attempt)
                    logger.info(
                        "Retrying %s OAuth %s in %.2fs",
                        self.provider_display_name,
                        endpoint_name,
                        wait_time,
                    )
                    await asyncio.sleep(wait_time)

        error_msg = (
            f"{self.provider_display_name} OAuth {endpoint_name} failed after "
            f"{self.max_retries + 1} attempts"
        )
        logger.error(error_msg)
        if last_exception is not None:
            raise last_exception
        raise OAuthNetworkError(
            message=error_msg,
            provider=self.provider_name,
            endpoint=endpoint_name,
        )
