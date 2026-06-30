# apps/api/routes/__init__.py

"""API route registry."""

from fastapi import APIRouter

from core.settings import settings
from routes.auth import router as auth_router
from routes.users import router as users_router
from routes.workspaces import router as workspaces_router

api_router = APIRouter(prefix=settings.API_V1_PREFIX)
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(workspaces_router)

__all__ = ["api_router"]
