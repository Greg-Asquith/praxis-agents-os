# apps/api/integrations/google_search_console/tools/schemas/__init__.py

"""Google Search Console tool input and output contracts."""

from .base import GoogleSearchConsoleStrictModel
from .inspection import GoogleSearchConsoleInspectUrlOutput
from .search_analytics import (
    GoogleSearchConsoleFilter,
    GoogleSearchConsoleSearchAnalyticsInput,
    GoogleSearchConsoleSearchAnalyticsOutput,
)
from .sitemap_submission import GoogleSearchConsoleSubmitSitemapsOutput
from .sitemaps import GoogleSearchConsoleListSitemapsOutput

__all__ = [
    "GoogleSearchConsoleFilter",
    "GoogleSearchConsoleInspectUrlOutput",
    "GoogleSearchConsoleListSitemapsOutput",
    "GoogleSearchConsoleSearchAnalyticsInput",
    "GoogleSearchConsoleSearchAnalyticsOutput",
    "GoogleSearchConsoleStrictModel",
    "GoogleSearchConsoleSubmitSitemapsOutput",
]
