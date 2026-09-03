# apps/api/integrations/google_search_console/tools/__init__.py

"""Google Search Console runtime-tool contributions."""

from services.agents.runtime.tools.contract import RuntimeToolDefinition

from .list_sitemaps import DEFINITION as LIST_SITEMAPS
from .query_search_analytics import DEFINITION as QUERY_SEARCH_ANALYTICS

TOOL_DEFINITIONS: tuple[RuntimeToolDefinition, ...] = (
    QUERY_SEARCH_ANALYTICS,
    LIST_SITEMAPS,
)

__all__ = ["TOOL_DEFINITIONS"]
