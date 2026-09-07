# apps/api/services/integrations/microsoft_graph/errors.py

"""Stable Microsoft Graph and Entra error classification."""

import logging
import re

import httpx2

from core.exceptions.integration import (
    IntegrationAuthError,
    IntegrationError,
    IntegrationFailureDisposition,
    IntegrationNotFoundError,
    IntegrationPermissionError,
    IntegrationRateLimitError,
    IntegrationValidationError,
)

logger = logging.getLogger(__name__)

_NOT_FOUND_CODES = frozenset({"itemNotFound", "ErrorItemNotFound", "ResourceNotFound"})
_PERMISSION_CODES = frozenset({"accessDenied", "ErrorAccessDenied", "notAllowed"})
_MAILBOX_UNAVAILABLE_CODES = frozenset({"MailboxNotEnabledForRESTAPI", "ErrorInvalidUser"})
_REAUTHORIZATION_CODES = frozenset({50076, 50079, 53003, 50173, 700082, 70008, 65001, 50105})
_CLIENT_CREDENTIAL_CODES = frozenset({7000215, 7000222})
_AADSTS_PREFIX = re.compile(r"^AADSTS(?P<code>\d+):")


def classify_entra_token_error(payload: dict[str, object]) -> str | None:
    """Return a stable recovery reason for a documented Entra token error."""
    code = _entra_error_code(payload)
    if code in _REAUTHORIZATION_CODES:
        return "reauthorization_required"
    if code in _CLIENT_CREDENTIAL_CODES:
        logger.error("Microsoft Graph OAuth client credential is invalid or expired")
        return "client_credential_invalid"
    return None


def graph_response_error(
    response: httpx2.Response,
    *,
    provider_key: str,
    operation: str,
) -> IntegrationError | None:
    """Map a Graph error body without exposing provider-controlled messages."""
    request_id = response.headers.get("request-id")
    if request_id:
        logger.debug("Microsoft Graph request failed", extra={"request_id": request_id})
    code = _graph_error_code(response)
    context = {
        "provider_key": provider_key,
        "operation": operation,
        "failure_disposition": IntegrationFailureDisposition.REJECTED,
    }
    if code in _NOT_FOUND_CODES:
        return IntegrationNotFoundError("Microsoft Graph resource was not found", **context)
    if code in _PERMISSION_CODES:
        return IntegrationPermissionError("Microsoft Graph operation was denied", **context)
    if code == "InvalidAuthenticationToken":
        return IntegrationAuthError("Microsoft Graph authentication failed", **context)
    if code in _MAILBOX_UNAVAILABLE_CODES:
        return IntegrationValidationError(
            "The Microsoft account has no available Outlook mailbox",
            error_code="mailbox_unavailable",
            **context,
        )
    if code == "activityLimitReached" and response.status_code != 429:
        return IntegrationRateLimitError("Microsoft Graph rate limit exceeded", **context)
    return None


def _entra_error_code(payload: dict[str, object]) -> int | None:
    values = payload.get("error_codes")
    if isinstance(values, list):
        for value in values:
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
    description = payload.get("error_description")
    if isinstance(description, str):
        match = _AADSTS_PREFIX.match(description)
        if match:
            return int(match.group("code"))
    return None


def _graph_error_code(response: httpx2.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    return code if isinstance(code, str) else None
