# apps/api/integrations/notion/entity_resolvers/__init__.py

"""Notion entity resolvers."""

from .data_source import NOTION_DATA_SOURCE_RESOLVER
from .page import NOTION_PAGE_RESOLVER

ENTITY_RESOLVERS = (NOTION_PAGE_RESOLVER, NOTION_DATA_SOURCE_RESOLVER)

__all__ = ["ENTITY_RESOLVERS", "NOTION_DATA_SOURCE_RESOLVER", "NOTION_PAGE_RESOLVER"]
