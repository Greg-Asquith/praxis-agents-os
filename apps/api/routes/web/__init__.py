# apps/api/routes/web/__init__.py

"""Web tool route registry."""

from fastapi import APIRouter

from routes.web.save_fetched_page import router as save_fetched_page_router

router = APIRouter(prefix="/web", tags=["web"])
router.include_router(save_fetched_page_router)

__all__ = ["router"]
