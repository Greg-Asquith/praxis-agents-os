# apps/api/integrations/notion/tools/__init__.py

"""Notion runtime-tool contributions."""

from .create_page import DEFINITION as CREATE_PAGE_DEFINITION
from .query_data_source import DEFINITION as QUERY_DATA_SOURCE_DEFINITION
from .read_page import DEFINITION as READ_PAGE_DEFINITION
from .search_pages import DEFINITION as SEARCH_PAGES_DEFINITION
from .update_page_content import DEFINITION as UPDATE_PAGE_CONTENT_DEFINITION
from .update_page_properties import DEFINITION as UPDATE_PAGE_PROPERTIES_DEFINITION

TOOL_DEFINITIONS = (
    SEARCH_PAGES_DEFINITION,
    READ_PAGE_DEFINITION,
    QUERY_DATA_SOURCE_DEFINITION,
    CREATE_PAGE_DEFINITION,
    UPDATE_PAGE_CONTENT_DEFINITION,
    UPDATE_PAGE_PROPERTIES_DEFINITION,
)

__all__ = ["TOOL_DEFINITIONS"]
