# apps/api/routes/agent_runs/__init__.py

"""Agent-run route registry."""

from fastapi import APIRouter

from routes.agent_runs.resume_run import router as resume_run_router

router = APIRouter(prefix="/agent-runs", tags=["agent-runs"])
router.include_router(resume_run_router)

__all__ = ["router"]
