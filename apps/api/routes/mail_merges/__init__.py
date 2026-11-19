# apps/api/routes/mail_merges/__init__.py

"""Mail merge progress and control routes."""

from fastapi import APIRouter, Depends

from core.dependencies import require_editor
from routes.mail_merges.cancel_mail_merge import router as cancel_router
from routes.mail_merges.get_mail_merge import router as get_router
from routes.mail_merges.pause_mail_merge import router as pause_router
from routes.mail_merges.resume_mail_merge import router as resume_router

# Read-only members can't send merges; services narrow further to the sender or an admin.
router = APIRouter(
    prefix="/mail-merges", tags=["mail-merges"], dependencies=[Depends(require_editor)]
)
router.include_router(get_router)
router.include_router(pause_router)
router.include_router(resume_router)
router.include_router(cancel_router)
