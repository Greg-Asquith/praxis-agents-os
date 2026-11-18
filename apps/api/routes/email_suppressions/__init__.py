# apps/api/routes/email_suppressions/__init__.py

"""Workspace Do Not Email list routes."""

from fastapi import APIRouter, Depends

from core.dependencies import require_editor
from routes.email_suppressions.add_email_suppressions import router as add_router
from routes.email_suppressions.list_email_suppressions import router as list_router
from routes.email_suppressions.remove_email_suppression import router as remove_router

# Read-only members can't see the list; removal narrows further to owners and admins.
router = APIRouter(
    prefix="/email-suppressions",
    tags=["email-suppressions"],
    dependencies=[Depends(require_editor)],
)
router.include_router(list_router)
router.include_router(add_router)
router.include_router(remove_router)
