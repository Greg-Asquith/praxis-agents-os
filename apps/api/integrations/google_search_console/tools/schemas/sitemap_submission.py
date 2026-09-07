# apps/api/integrations/google_search_console/tools/schemas/sitemap_submission.py

"""Typed contracts for Search Console sitemap submissions."""

from typing import Literal

from pydantic import Field

from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from .base import GoogleSearchConsoleStrictModel


class GoogleSearchConsoleSitemapSubmissionResult(GoogleSearchConsoleStrictModel):
    sitemap_url: str = Field(min_length=1, max_length=4_096)
    outcome: Literal["submitted", "failed", "unverified"]
    previously_submitted: bool
    last_submitted: str | None = Field(default=None, max_length=128)
    is_pending: bool | None = None
    warnings: int | None = Field(default=None, ge=0)
    errors: int | None = Field(default=None, ge=0)
    status_read: bool
    error_code: Literal["rejected", "unverified", "status_unavailable"] | None = None
    message: str | None = Field(default=None, max_length=1_000)


class GoogleSearchConsoleSubmitSitemapsData(GoogleSearchConsoleStrictModel):
    sitemaps: list[GoogleSearchConsoleSitemapSubmissionResult] = Field(max_length=20)
    submitted_count: int = Field(ge=0, le=20)
    failed_count: int = Field(ge=0, le=20)


class GoogleSearchConsoleSubmitSitemapsEntry(IntegrationFanOutEntry):
    data: GoogleSearchConsoleSubmitSitemapsData | None = None


class GoogleSearchConsoleSubmitSitemapsOutput(IntegrationFanOutOutput):
    results: list[GoogleSearchConsoleSubmitSitemapsEntry]
