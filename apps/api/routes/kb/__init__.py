# apps/api/routes/kb/__init__.py

"""Knowledge-base route registry."""

from fastapi import APIRouter

from routes.kb.create_document import router as create_document_router
from routes.kb.create_document_from_file import router as create_document_from_file_router
from routes.kb.create_document_from_url import router as create_document_from_url_router
from routes.kb.delete_document import router as delete_document_router
from routes.kb.get_document import router as get_document_router
from routes.kb.list_documents import router as list_documents_router
from routes.kb.reprocess_document import router as reprocess_document_router
from routes.kb.search import router as search_router
from routes.kb.update_document import router as update_document_router

router = APIRouter(prefix="/kb", tags=["kb"])
router.include_router(search_router)
router.include_router(list_documents_router)
router.include_router(get_document_router)
router.include_router(create_document_router)
router.include_router(create_document_from_url_router)
router.include_router(create_document_from_file_router)
router.include_router(update_document_router)
router.include_router(delete_document_router)
router.include_router(reprocess_document_router)

__all__ = ["router"]
