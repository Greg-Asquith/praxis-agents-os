# apps/api/integrations/google_search_console/tools/__init__.py

"""Google Search Console runtime-tool contributions."""

from services.agents.runtime.tools.contract import RuntimeToolDefinition

from .inspect_url import DEFINITION as INSPECT_URL
from .list_sitemaps import DEFINITION as LIST_SITEMAPS
from .query_search_analytics import DEFINITION as QUERY_SEARCH_ANALYTICS

TOOL_DEFINITIONS: tuple[RuntimeToolDefinition, ...] = (
    QUERY_SEARCH_ANALYTICS,
    LIST_SITEMAPS,
    INSPECT_URL,
)

__all__ = ["TOOL_DEFINITIONS"]
