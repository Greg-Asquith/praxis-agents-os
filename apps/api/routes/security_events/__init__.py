# apps/api/routes/security_events/__init__.py

"""Security-event route registry."""

from fastapi import APIRouter, Depends

from core.dependencies import require_super_admin
from routes.security_events.get_security_event import router as get_security_event_router
from routes.security_events.list_security_events import router as list_security_events_router

router = APIRouter(
    prefix="/security-events",
    tags=["security-events"],
    dependencies=[Depends(require_super_admin)],
)
router.include_router(list_security_events_router)
router.include_router(get_security_event_router)

__all__ = ["router"]
