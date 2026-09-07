# apps/api/integrations/google_search_console/tools/schemas/sitemaps.py

"""Typed contracts for Search Console sitemap status."""

from pydantic import Field

from services.agents.runtime.untrusted import UntrustedNode
from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from .base import GoogleSearchConsoleStrictModel


class GoogleSearchConsoleSitemapContent(GoogleSearchConsoleStrictModel):
    type: str = Field(max_length=128)
    submitted: int = Field(ge=0)


class GoogleSearchConsoleSitemap(GoogleSearchConsoleStrictModel):
    path: UntrustedNode
    type: str = Field(max_length=128)
    last_submitted: str | None = Field(default=None, max_length=128)
    last_downloaded: str | None = Field(default=None, max_length=128)
    is_pending: bool
    is_sitemaps_index: bool
    warnings: int = Field(ge=0)
    errors: int = Field(ge=0)
    contents: list[GoogleSearchConsoleSitemapContent] = Field(max_length=20)
    submitted_url_count: int = Field(ge=0)


class GoogleSearchConsoleSitemapsData(GoogleSearchConsoleStrictModel):
    sitemaps: list[GoogleSearchConsoleSitemap] = Field(max_length=200)
    sitemap_count: int = Field(ge=0, le=200)


class GoogleSearchConsoleSitemapsEntry(IntegrationFanOutEntry):
    data: GoogleSearchConsoleSitemapsData | None = None


class GoogleSearchConsoleListSitemapsOutput(IntegrationFanOutOutput):
    results: list[GoogleSearchConsoleSitemapsEntry]
