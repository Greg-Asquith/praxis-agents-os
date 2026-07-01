# apps/api/routes/storage/__init__.py

"""Storage route registry."""

from fastapi import APIRouter

from routes.storage.private_object import router as private_object_router
from routes.storage.public_object import router as public_object_router
from routes.storage.upload_object import router as upload_object_router

router = APIRouter(prefix="/storage", tags=["storage"])
router.include_router(public_object_router)
router.include_router(private_object_router)
router.include_router(upload_object_router)

__all__ = ["router"]
