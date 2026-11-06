# apps/api/utils/isolated_service.py

"""Posts one operation to an isolated service built on the shared isolation driver."""

import asyncio
from dataclasses import dataclass
from typing import Any, Literal

import httpx2 as httpx
from pydantic import SecretStr

IsolatedServiceAuth = Literal["google_id_token", "shared_secret", "none"]


class IsolatedServiceError(Exception):
    """A service failure with a stable code and a message safe to show an agent."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class IsolatedService:
    """Where one isolated service listens, how to authenticate, and how to name its failures."""

    label: str
    url: str
    auth: IsolatedServiceAuth
    shared_secret: SecretStr
    error: type[IsolatedServiceError] = IsolatedServiceError


async def post_isolated_operation(
    service: IsolatedService, payload: dict[str, Any], *, request_seconds: float
) -> dict[str, Any]:
    """Returns the service's response body, raising ``service.error`` unless it reports ok."""
    try:
        async with httpx.AsyncClient(timeout=request_seconds) as client:
            response = await client.post(
                f"{service.url}/v1/operations",
                json=payload,
                headers=await _auth_headers(service),
            )
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise service.error("unavailable", f"The {service.label} couldn't be reached.") from exc
    if not isinstance(body, dict):
        raise service.error("invalid_response", f"The {service.label} gave an invalid answer.")
    if response.status_code != 200 or body.get("ok") is not True:
        error = body.get("error") if isinstance(body.get("error"), dict) else {}
        raise service.error(
            str(error.get("code") or "failed")[:64],
            str(error.get("message") or f"The {service.label} failed.")[:300],
        )
    return body


async def _auth_headers(service: IsolatedService) -> dict[str, str]:
    if service.auth == "none":
        return {}
    if service.auth == "shared_secret":
        return {"authorization": f"Bearer {service.shared_secret.get_secret_value()}"}
    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import id_token
    except ImportError as exc:
        raise service.error("unavailable", f"The {service.label} isn't available.") from exc
    token = await asyncio.to_thread(id_token.fetch_id_token, Request(), service.url)
    return {"authorization": f"Bearer {token}"}
