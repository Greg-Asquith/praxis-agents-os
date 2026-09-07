# apps/api/integrations/google_search_console/tools/schemas/inspection.py

"""Typed contracts for Search Console URL inspection."""

from pydantic import Field

from services.agents.runtime.untrusted import UntrustedNode
from services.integrations.context.results import IntegrationFanOutEntry, IntegrationFanOutOutput

from .base import GoogleSearchConsoleStrictModel


class GoogleSearchConsoleRichResult(GoogleSearchConsoleStrictModel):
    type: str = Field(max_length=128)
    issue_count: int = Field(ge=0)


class GoogleSearchConsoleInspection(GoogleSearchConsoleStrictModel):
    url: str = Field(max_length=4_096)
    verdict: str = Field(max_length=128)
    coverage_state: str = Field(max_length=128)
    robots_txt_state: str = Field(max_length=128)
    indexing_state: str = Field(max_length=128)
    page_fetch_state: str = Field(max_length=128)
    crawled_as: str = Field(max_length=128)
    last_crawl_time: str = Field(max_length=128)
    google_canonical: UntrustedNode | None = None
    user_canonical: UntrustedNode | None = None
    sitemap: list[UntrustedNode] = Field(default_factory=list, max_length=20)
    referring_urls: list[UntrustedNode] = Field(default_factory=list, max_length=20)
    mobile_usability_verdict: str = Field(max_length=128)
    rich_results_verdict: str = Field(max_length=128)
    rich_results: list[GoogleSearchConsoleRichResult] = Field(default_factory=list, max_length=20)
    inspection_result_link: str = Field(max_length=4_096)
    error_code: str | None = Field(default=None, max_length=128)
    message: UntrustedNode | None = None


class GoogleSearchConsoleInspectionData(GoogleSearchConsoleStrictModel):
    inspections: list[GoogleSearchConsoleInspection] = Field(min_length=1, max_length=10)


class GoogleSearchConsoleInspectionEntry(IntegrationFanOutEntry):
    data: GoogleSearchConsoleInspectionData | None = None


class GoogleSearchConsoleInspectUrlOutput(IntegrationFanOutOutput):
    results: list[GoogleSearchConsoleInspectionEntry]
