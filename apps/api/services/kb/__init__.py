# apps/api/services/kb/__init__.py

"""Knowledge-base service operations."""

from services.kb.create_document import create_kb_document
from services.kb.delete_document import delete_kb_document
from services.kb.get_document import get_kb_document
from services.kb.search_chunks import search_chunks

__all__ = [
    "create_kb_document",
    "delete_kb_document",
    "get_kb_document",
    "search_chunks",
]
