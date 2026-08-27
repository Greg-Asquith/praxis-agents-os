# apps/api/integrations/notion/tools/__init__.py

"""Notion runtime-tool contributions."""

from .query_data_source import DEFINITION as QUERY_DATA_SOURCE_DEFINITION
from .read_page import DEFINITION as READ_PAGE_DEFINITION
from .search_pages import DEFINITION as SEARCH_PAGES_DEFINITION

TOOL_DEFINITIONS = (
    SEARCH_PAGES_DEFINITION,
    READ_PAGE_DEFINITION,
    QUERY_DATA_SOURCE_DEFINITION,
)

__all__ = ["TOOL_DEFINITIONS"]
