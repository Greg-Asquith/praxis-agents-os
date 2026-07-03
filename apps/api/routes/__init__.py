# apps/api/routes/__init__.py

"""API route registry."""

from fastapi import APIRouter

from core.settings import settings
from routes.agent_runs import router as agent_runs_router
from routes.agents import router as agents_router
from routes.audit_events import router as audit_events_router
from routes.auth import router as auth_router
from routes.conversations import router as conversations_router
from routes.models import router as models_router
from routes.schedules import router as schedules_router
from routes.security_events import router as security_events_router
from routes.storage import router as storage_router
from routes.users import router as users_router
from routes.workspaces import router as workspaces_router

api_router = APIRouter(prefix=settings.API_V1_PREFIX)
api_router.include_router(agent_runs_router)
api_router.include_router(agents_router)
api_router.include_router(audit_events_router)
api_router.include_router(auth_router)
api_router.include_router(conversations_router)
api_router.include_router(models_router)
api_router.include_router(schedules_router)
api_router.include_router(security_events_router)
api_router.include_router(storage_router)
api_router.include_router(users_router)
api_router.include_router(workspaces_router)

__all__ = ["api_router"]
