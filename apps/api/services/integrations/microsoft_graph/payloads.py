# apps/api/services/integrations/microsoft_graph/payloads.py

"""Small validation helpers for Microsoft Graph JSON objects."""

from core.exceptions.integration import IntegrationValidationError


def graph_string(payload: object, key: str) -> str:
    """Return a trimmed Graph string field or an empty value."""
    if not isinstance(payload, dict):
        return ""
    value = payload.get(key)
    return value.strip() if isinstance(value, str) else ""


def required_graph_string(
    payload: object,
    key: str,
    *,
    provider_key: str,
) -> str:
    """Return a required Graph string field or reject the response."""
    value = graph_string(payload, key)
    if value:
        return value
    raise IntegrationValidationError(
        "Microsoft Graph discovery returned an invalid response",
        provider_key=provider_key,
        operation="discover_resources",
    )
