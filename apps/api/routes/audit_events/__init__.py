# apps/api/routes/audit_events/__init__.py

"""Audit-event route registry."""

from fastapi import APIRouter, Depends

from core.dependencies import require_owner
from routes.audit_events.get_audit_event import router as get_audit_event_router
from routes.audit_events.list_audit_events import router as list_audit_events_router

router = APIRouter(
    prefix="/audit-events",
    tags=["audit-events"],
    dependencies=[Depends(require_owner)],
)
router.include_router(list_audit_events_router)
router.include_router(get_audit_event_router)

__all__ = ["router"]
