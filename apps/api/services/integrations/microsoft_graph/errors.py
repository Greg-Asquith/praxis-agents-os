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
_WRITE_ERRORS = {
    409: ("name_exists", "A file with this name exists. Replace it or choose another name."),
    412: ("version_conflict", "The item changed. Read it again before replacing it."),
    416: (
        "invalid_range",
        "The upload range was rejected. Check the upload status before continuing.",
    ),
    423: ("locked", "The item is locked. Try again after the lock is released."),
    507: (
        "quota_exceeded",
        "There is insufficient storage. Free space before trying again.",
    ),
}


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
    write_error = graph_write_error(
        response,
        provider_key=provider_key,
        operation=operation,
        name_conflict=code == "nameAlreadyExists",
    )
    if write_error is not None:
        return write_error
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


def graph_write_error(
    response: httpx2.Response, *, provider_key: str, operation: str, name_conflict: bool
) -> IntegrationValidationError | None:
    """Classifies write conflicts without retaining provider response content."""
    if response.status_code == 409 and not name_conflict:
        return None
    detail = _WRITE_ERRORS.get(response.status_code)
    if detail is None:
        return None
    error_code, message = detail
    return IntegrationValidationError(
        message,
        provider_key=provider_key,
        operation=operation,
        error_code=error_code,
        failure_disposition=IntegrationFailureDisposition.REJECTED,
    )


def upload_response_error(
    response: httpx2.Response, *, provider_key: str, operation: str
) -> IntegrationError | None:
    """Classifies a signed upload response without logging its identifiers."""
    if response.status_code == 404:
        return IntegrationNotFoundError(
            "The upload session expired. Start the upload again.",
            provider_key=provider_key,
            operation=operation,
            error_code="upload_session_expired",
            failure_disposition=IntegrationFailureDisposition.NOT_DISPATCHED,
        )
    return graph_write_error(
        response,
        provider_key=provider_key,
        operation=operation,
        name_conflict=_graph_error_code(response) == "nameAlreadyExists",
    )


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
