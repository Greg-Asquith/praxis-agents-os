# apps/api/routes/kb/platform/__init__.py

"""Platform knowledge route registry."""

from fastapi import APIRouter

from routes.kb.platform.create_document_from_file import router as create_document_from_file_router
from routes.kb.platform.create_manual_document import router as create_manual_document_router
from routes.kb.platform.delete_document import router as delete_document_router
from routes.kb.platform.get_document import router as get_document_router
from routes.kb.platform.list_documents import router as list_documents_router
from routes.kb.platform.publish_document import router as publish_document_router
from routes.kb.platform.reprocess_document import router as reprocess_document_router
from routes.kb.platform.update_document import router as update_document_router
from routes.kb.platform.withdraw_document import router as withdraw_document_router

router = APIRouter(prefix="/platform/documents")
router.include_router(create_manual_document_router)
router.include_router(create_document_from_file_router)
router.include_router(get_document_router)
router.include_router(list_documents_router)
router.include_router(update_document_router)
router.include_router(reprocess_document_router)
router.include_router(publish_document_router)
router.include_router(withdraw_document_router)
router.include_router(delete_document_router)

__all__ = ["router"]
