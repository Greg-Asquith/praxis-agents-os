# apps/api/integrations/google_search_console/operations/publish_url_notification.py

"""Publish one eligible URL notification through Google's Indexing API."""

from typing import Literal

from core.exceptions.integration import (
    IntegrationFailureDisposition,
    IntegrationValidationError,
)
from services.integrations.http import IntegrationRequestPolicy

from ..client import GoogleSearchConsoleClient


async def publish_url_notification(
    client: GoogleSearchConsoleClient,
    *,
    url: str,
    notification_type: Literal["URL_UPDATED", "URL_DELETED"],
) -> None:
    payload = await client.indexing_post(
        "urlNotifications:publish",
        operation="publish_url_notification",
        policy=IntegrationRequestPolicy.MUTATION,
        json={"url": url, "type": notification_type},
    )
    if not isinstance(payload, dict):
        raise IntegrationValidationError(
            "Google's Indexing API returned an invalid notification response",
            provider_key="google_search_console",
            operation="publish_url_notification",
            failure_disposition=IntegrationFailureDisposition.AMBIGUOUS,
        )
