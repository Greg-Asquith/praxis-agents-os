# apps/api/services/kb/platform/__init__.py

"""Platform knowledge management operations."""

from services.kb.platform.create_document_from_file import create_document_from_file
from services.kb.platform.create_manual_document import create_manual_document
from services.kb.platform.delete_document import delete_document
from services.kb.platform.get_document import get_document
from services.kb.platform.list_documents import list_documents
from services.kb.platform.publish_document import publish_document
from services.kb.platform.reprocess_document import reprocess_document
from services.kb.platform.update_document import update_document
from services.kb.platform.withdraw_document import withdraw_document

__all__ = [
    "create_document_from_file",
    "create_manual_document",
    "delete_document",
    "get_document",
    "list_documents",
    "publish_document",
    "reprocess_document",
    "update_document",
    "withdraw_document",
]
