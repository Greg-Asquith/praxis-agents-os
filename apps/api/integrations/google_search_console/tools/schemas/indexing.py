# apps/api/integrations/google_search_console/tools/schemas/indexing.py

"""Typed contracts for Google Indexing API notifications."""

from typing import Literal

from pydantic import Field

from integrations.google_search_console.references import MAX_SEARCH_CONSOLE_URL_LENGTH
from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from .base import GoogleSearchConsoleStrictModel


class GoogleSearchConsoleIndexingNotification(GoogleSearchConsoleStrictModel):
    url: str = Field(min_length=1, max_length=MAX_SEARCH_CONSOLE_URL_LENGTH)
    notification_type: Literal["URL_UPDATED", "URL_DELETED"]
    page_type: Literal["job_posting", "broadcast_event"]


class GoogleSearchConsoleIndexingResult(GoogleSearchConsoleIndexingNotification):
    outcome: Literal["notified", "failed", "unverified"]
    notify_time: str | None = Field(default=None, max_length=128)
    error_code: (
        Literal[
            "not_owner",
            "scope_missing",
            "api_not_enabled",
            "quota_exhausted",
            "rejected",
            "unverified",
            "status_unavailable",
        ]
        | None
    ) = None
    message: str | None = Field(default=None, max_length=1_000)


class GoogleSearchConsoleRequestIndexingData(GoogleSearchConsoleStrictModel):
    notifications: list[GoogleSearchConsoleIndexingResult] = Field(max_length=20)
    notified_count: int = Field(ge=0, le=20)
    failed_count: int = Field(ge=0, le=20)


class GoogleSearchConsoleRequestIndexingEntry(IntegrationFanOutEntry):
    data: GoogleSearchConsoleRequestIndexingData | None = None


class GoogleSearchConsoleRequestIndexingOutput(IntegrationFanOutOutput):
    results: list[GoogleSearchConsoleRequestIndexingEntry]
