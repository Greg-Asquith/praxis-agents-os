# apps/api/integrations/google_search_console/operations/get_url_notification_metadata.py

"""Read the latest notification metadata for one URL."""

from collections.abc import Mapping
from typing import Literal

from core.exceptions.integration import IntegrationNotFoundError, IntegrationValidationError
from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleSearchConsoleClient


async def get_url_notification_metadata(
    client: GoogleSearchConsoleClient,
    *,
    url: str,
    notification_type: Literal["URL_UPDATED", "URL_DELETED"],
) -> dict[str, str | None] | None:
    try:
        payload = await client.indexing_get(
            "urlNotifications/metadata",
            operation="get_url_notification_metadata",
            policy=IntegrationRequestPolicy.READ,
            params={"url": url},
        )
    except IntegrationNotFoundError:
        return None
    if not isinstance(payload, dict) or payload.get("url") != url:
        raise _invalid_metadata()
    key = "latestUpdate" if notification_type == "URL_UPDATED" else "latestRemove"
    notification = payload.get(key)
    if notification is None:
        return None
    if not isinstance(notification, Mapping):
        raise _invalid_metadata()
    returned_type = notification.get("type")
    notify_time = notification.get("notifyTime")
    if returned_type != notification_type or not isinstance(notify_time, str) or not notify_time:
        raise _invalid_metadata()
    return {"url": url, "notification_type": returned_type, "notify_time": notify_time[:128]}


def _invalid_metadata() -> IntegrationValidationError:
    return IntegrationValidationError(
        "Google's Indexing API returned invalid notification metadata",
        provider_key="google_search_console",
        operation="get_url_notification_metadata",
    )
