# apps/api/integrations/google_search_console/tools/schemas/__init__.py

"""Google Search Console tool input and output contracts."""

from .base import GoogleSearchConsoleStrictModel
from .search_analytics import (
    GoogleSearchConsoleFilter,
    GoogleSearchConsoleSearchAnalyticsInput,
    GoogleSearchConsoleSearchAnalyticsOutput,
)
from .sitemaps import GoogleSearchConsoleListSitemapsOutput

__all__ = [
    "GoogleSearchConsoleFilter",
    "GoogleSearchConsoleListSitemapsOutput",
    "GoogleSearchConsoleSearchAnalyticsInput",
    "GoogleSearchConsoleSearchAnalyticsOutput",
    "GoogleSearchConsoleStrictModel",
]
