# apps/api/routes/kb/__init__.py

"""Knowledge-base route registry."""

from fastapi import APIRouter

from routes.kb.get_document import router as get_document_router
from routes.kb.search import router as search_router

router = APIRouter(prefix="/kb", tags=["kb"])
router.include_router(search_router)
router.include_router(get_document_router)

__all__ = ["router"]
