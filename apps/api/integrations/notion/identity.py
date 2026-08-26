# apps/api/integrations/notion/identity.py

"""Resolve the user and workspace represented by a Notion OAuth grant."""

from typing import Any

from core.exceptions.integration import IntegrationAuthError
from services.integrations.http import IntegrationRequestPolicy
from services.integrations.plugin import ExternalPrincipal

from .client import NOTION_API_VERSION, NotionClient, fixed_access_token


def extract_token_identity(payload: dict[str, Any]) -> ExternalPrincipal:
    """Extract the grant identity and bounded metadata from a token response."""
    for field_name in ("access_token", "refresh_token", "workspace_id", "bot_id"):
        _required_string(payload, field_name, operation="oauth_token_exchange")

    workspace_id = _required_string(payload, "workspace_id", operation="oauth_token_exchange")
    bot_id = _required_string(payload, "bot_id", operation="oauth_token_exchange")
    owner_user_id = _owner_user_id(payload.get("owner"), operation="oauth_token_exchange")
    workspace_name = payload.get("workspace_name")
    if workspace_name is not None and not isinstance(workspace_name, str):
        raise _identity_error("oauth_token_exchange")
    bounded_name = workspace_name.strip()[:255] if workspace_name else ""

    metadata = {
        "workspace_id": workspace_id,
        "workspace_name": bounded_name,
        "bot_id": bot_id,
        "owner_user_id": owner_user_id,
        "api_version": NOTION_API_VERSION,
    }
    return ExternalPrincipal(
        external_id=f"{workspace_id}:{owner_user_id}",
        label=bounded_name or None,
        connection_metadata=metadata,
    )


async def fetch_token_identity(access_token: str) -> ExternalPrincipal:
    """Fetch the grant identity from Notion's authenticated bot endpoint."""
    payload = await NotionClient(fixed_access_token(access_token)).get(
        "users/me",
        operation="oauth_identity",
        policy=IntegrationRequestPolicy.READ,
    )
    try:
        workspace_id, bot_id, owner_user_id = parse_user_identity(payload)
    except TypeError:
        raise _identity_error("oauth_identity") from None
    return ExternalPrincipal(
        external_id=f"{workspace_id}:{owner_user_id}",
        label=None,
        connection_metadata={
            "workspace_id": workspace_id,
            "bot_id": bot_id,
            "owner_user_id": owner_user_id,
            "api_version": NOTION_API_VERSION,
        },
    )


def parse_user_identity(payload: Any) -> tuple[str, str, str]:
    """Parse stable identifiers from Notion's authenticated bot response."""
    if not isinstance(payload, dict):
        raise TypeError("Invalid Notion bot identity")
    bot = payload.get("bot")
    if not isinstance(bot, dict):
        raise TypeError("Invalid Notion bot identity")
    try:
        workspace_id = _required_string(bot, "workspace_id", operation="oauth_identity")
        bot_id = _required_string(payload, "id", operation="oauth_identity")
        owner_user_id = _owner_user_id(bot.get("owner"), operation="oauth_identity")
    except IntegrationAuthError:
        raise TypeError("Invalid Notion bot identity") from None
    return workspace_id, bot_id, owner_user_id


def _owner_user_id(value: Any, *, operation: str) -> str:
    if not isinstance(value, dict) or value.get("type") != "user":
        raise _identity_error(operation)
    user = value.get("user")
    if not isinstance(user, dict):
        raise _identity_error(operation)
    return _required_string(user, "id", operation=operation)


def _required_string(payload: dict[str, Any], key: str, *, operation: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _identity_error(operation)
    return value.strip()


def _identity_error(operation: str) -> IntegrationAuthError:
    return IntegrationAuthError(
        "Notion identity response was rejected",
        provider_key="notion",
        operation=operation,
    )
