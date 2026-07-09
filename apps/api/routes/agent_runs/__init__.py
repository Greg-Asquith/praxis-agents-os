# apps/api/routes/agent_runs/__init__.py

"""Agent-run route registry."""

from fastapi import APIRouter

from routes.agent_runs.cancel_run import router as cancel_run_router
from routes.agent_runs.get_approval_state import router as get_approval_state_router
from routes.agent_runs.resume_run import router as resume_run_router

router = APIRouter(prefix="/agent-runs", tags=["agent-runs"])
router.include_router(cancel_run_router)
router.include_router(get_approval_state_router)
router.include_router(resume_run_router)

__all__ = ["router"]
