# apps/api/routes/agents/__init__.py

"""Agent route registry."""

from fastapi import APIRouter

from routes.agents.create_agent import router as create_agent_router
from routes.agents.delete_agent import router as delete_agent_router
from routes.agents.get_agent import router as get_agent_router
from routes.agents.list_agents import router as list_agents_router
from routes.agents.update_agent import router as update_agent_router

router = APIRouter(prefix="/agents", tags=["agents"])
router.include_router(list_agents_router)
router.include_router(create_agent_router)
router.include_router(get_agent_router)
router.include_router(update_agent_router)
router.include_router(delete_agent_router)

__all__ = ["router"]
